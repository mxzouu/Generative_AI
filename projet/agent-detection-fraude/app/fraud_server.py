"""Serveur MCP « fraude » (transport stdio) — la boîte à outils de l'agent.

Calqué sur notebooks/TD4_mcp/mini_project/pim_server.py : FastMCP + ChromaDB persistant.
Au démarrage : charge data/claims.csv, calcule les features (ml/features.py), charge le
modèle de scoring persisté (models/fraud_model.joblib — l'entraîne s'il manque), et
(re)construit l'index ChromaDB des sinistres pour le RAG (embeddings all-MiniLM-L6-v2).

Garde-fou : `score_claim` et `flag_claim` PROPOSENT ; seul `validate_case` — appelé sur
ordre explicite du conseiller — committe un verdict. Aucun label « fraude » automatique.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import pandas as pd
from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

logging.getLogger("mcp").setLevel(logging.WARNING)

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from ml.model import FraudModel  # noqa: E402
from ml.features import engineer  # noqa: E402

CLAIMS_CSV = PROJECT / "data" / "claims.csv"
DECISIONS_JSON = PROJECT / "data" / "decisions.json"
MODEL_PATH = PROJECT / "models" / "fraud_model.joblib"
CHROMA_PATH = PROJECT / "chroma_index"
COLLECTION_NAME = "claims"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # même espace vectoriel que TD1 -> TD5

# ---------------------------------------------------------------------------
# État : le CSV des sinistres + features pré-calculées + modèle + index Chroma.
# ---------------------------------------------------------------------------
claims = pd.read_csv(CLAIMS_CSV, dtype={"label": "string"}).fillna({"label": ""})
features = engineer(claims)  # indexé par claim_id, même contexte au train et au serving

if MODEL_PATH.exists():
    model = FraudModel.load(MODEL_PATH)
else:  # premier lancement : entraîne sur les sinistres historiques étiquetés
    model = FraudModel()
    model.train(claims)
    model.save(MODEL_PATH)

embed_model = SentenceTransformer(EMBED_MODEL_NAME)
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

if COLLECTION_NAME in [c.name for c in chroma_client.list_collections()]:
    collection = chroma_client.get_collection(COLLECTION_NAME)
    if collection.count() != len(claims):  # dataset regénéré -> on repart de zéro
        chroma_client.delete_collection(COLLECTION_NAME)
        collection = chroma_client.create_collection(COLLECTION_NAME)
else:
    collection = chroma_client.create_collection(COLLECTION_NAME)

if collection.count() == 0:
    docs = (claims["type"] + " — " + claims["description"]).tolist()
    embeddings = embed_model.encode(docs, show_progress_bar=False)
    collection.add(
        ids=claims["claim_id"].tolist(),
        embeddings=embeddings.tolist(),
        documents=docs,
        metadatas=[
            {
                "date": r["date"],
                "customer_id": r["customer_id"],
                "type": r["type"],
                "amount": float(r["amount"]),
                "label": r["label"] or "new",
                "status": "confirmed" if r["label"] else "new",
            }
            for _, r in claims.iterrows()
        ],
    )


# ---------------------------------------------------------------------------
# Journal des décisions (flags, validations, demandes de pièces) — piste d'audit.
# ---------------------------------------------------------------------------
def _load_decisions() -> dict:
    if DECISIONS_JSON.exists():
        return json.loads(DECISIONS_JSON.read_text(encoding="utf-8"))
    return {"flags": [], "validations": [], "document_requests": []}


def _log_decision(kind: str, entry: dict) -> None:
    decisions = _load_decisions()
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    decisions[kind].append(entry)
    DECISIONS_JSON.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")


def _claim_row(claim_id: str) -> pd.Series | None:
    hits = claims[claims["claim_id"] == claim_id]
    return hits.iloc[0] if len(hits) else None


def _claim_dict(row: pd.Series, full: bool = True) -> dict:
    d = row.to_dict()
    d["amount"] = float(d["amount"])
    if not full:
        keep = ("claim_id", "date", "customer_id", "type", "amount", "incident_date", "label")
        d = {k: d[k] for k in keep} | {"description": row["description"][:120]}
    return d


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------
mcp_server = FastMCP("fraud")


@mcp_server.tool()
def get_claims(date: str) -> list:
    """Liste les sinistres déclarés à une date (format YYYY-MM-DD) : le briefing matinal."""
    subset = claims[claims["date"] == date]
    return [_claim_dict(r, full=False) for _, r in subset.iterrows()]


@mcp_server.tool()
def get_claim(claim_id: str) -> dict:
    """Détail complet d'un sinistre (montant, dates, police, IBAN, description...)."""
    row = _claim_row(claim_id)
    return _claim_dict(row) if row is not None else {"error": f"sinistre {claim_id} introuvable"}


@mcp_server.tool()
def get_customer_history(customer_id: str) -> list:
    """Tous les sinistres passés d'un assuré, triés par date."""
    subset = claims[claims["customer_id"] == customer_id].sort_values("date")
    return [_claim_dict(r, full=False) for _, r in subset.iterrows()]


@mcp_server.tool()
def score_claim(claim_id: str) -> dict:
    """Score de fraude ML d'un sinistre : { probability, risk_band, top_factors }.

    Le score vient d'un modèle de régression logistique entraîné sur les fraudes
    confirmées ; top_factors liste les facteurs qui ont pesé sur CETTE prédiction
    (contribution positive = augmente le risque). C'est une suspicion, pas un verdict.
    """
    if claim_id not in features.index:
        return {"error": f"sinistre {claim_id} introuvable"}
    return {"claim_id": claim_id, **model.score(features.loc[claim_id])}


@mcp_server.tool()
def score_claims(date: str) -> list:
    """Score ML de TOUS les sinistres d'une date, triés par probabilité de fraude décroissante.

    À utiliser pour le briefing (un seul appel au lieu d'un score_claim par sinistre).
    Renvoie pour chaque sinistre : claim_id, probability, risk_band, top_factors (top 3).
    """
    subset = claims[claims["date"] == date]
    scored = [
        {"claim_id": r["claim_id"], "customer_id": r["customer_id"], "type": r["type"],
         "amount": float(r["amount"]), **model.score(features.loc[r["claim_id"]], top_n=3)}
        for _, r in subset.iterrows()
    ]
    return sorted(scored, key=lambda s: -s["probability"])


@mcp_server.tool()
def search_similar_claims(query: str, k: int = 5) -> list:
    """RAG : sinistres passés sémantiquement proches de la requête (dont fraudes confirmées).

    Utile pour comparer un sinistre du jour aux modes opératoires déjà vus : passe la
    description du sinistre comme requête et regarde le label des voisins renvoyés.
    """
    q_vec = embed_model.encode(query).tolist()
    res = collection.query(query_embeddings=[q_vec], n_results=min(k, collection.count()))
    return [
        {"claim_id": cid, "document": doc, "distance": round(float(dist), 3), **meta}
        for cid, doc, dist, meta in zip(res["ids"][0], res["documents"][0],
                                        res["distances"][0], res["metadatas"][0])
    ]


@mcp_server.tool()
def find_shared_identifiers(claim_id: str) -> dict:
    """Autres sinistres partageant le même IBAN / téléphone / adresse (détection de rings).

    Un même identifiant chez des assurés DIFFÉRENTS est un signal fort de réseau organisé.
    """
    row = _claim_row(claim_id)
    if row is None:
        return {"error": f"sinistre {claim_id} introuvable"}
    out: dict = {"claim_id": claim_id}
    for col in ("iban", "phone", "address"):
        matches = claims[(claims[col] == row[col]) & (claims["claim_id"] != claim_id)]
        out[col] = [
            {"claim_id": r["claim_id"], "customer_id": r["customer_id"], "date": r["date"],
             "label": r["label"] or "new",
             "same_customer": bool(r["customer_id"] == row["customer_id"])}
            for _, r in matches.iterrows()
        ]
    return out


@mcp_server.tool()
def request_document(claim_id: str, doc_type: str) -> dict:
    """Enregistre une demande de pièce au client (facture, constat, photos...). Loggée, pas envoyée."""
    if _claim_row(claim_id) is None:
        return {"error": f"sinistre {claim_id} introuvable"}
    _log_decision("document_requests", {"claim_id": claim_id, "doc_type": doc_type})
    return {"status": "logged", "claim_id": claim_id, "doc_type": doc_type}


@mcp_server.tool()
def flag_claim(claim_id: str, score: float, reason: str) -> dict:
    """Marque un sinistre comme suspect (PROPOSITION à valider par le conseiller, pas une décision)."""
    if _claim_row(claim_id) is None:
        return {"error": f"sinistre {claim_id} introuvable"}
    _log_decision("flags", {"claim_id": claim_id, "score": score, "reason": reason})
    collection.update(ids=[claim_id], metadatas=[{"status": "flagged"}])
    return {"status": "flagged", "claim_id": claim_id, "note": "en attente de validation humaine"}


@mcp_server.tool()
def validate_case(claim_id: str, verdict: str) -> dict:
    """Décision du CONSEILLER : verdict 'fraud_confirmed' ou 'false_positive'.

    À n'appeler QUE si le conseiller l'a explicitement demandé (human-in-the-loop).
    Une fraude confirmée devient un exemple étiqueté, visible du RAG des analyses suivantes.
    """
    if verdict not in ("fraud_confirmed", "false_positive"):
        return {"error": "verdict doit être 'fraud_confirmed' ou 'false_positive'"}
    row = _claim_row(claim_id)
    if row is None:
        return {"error": f"sinistre {claim_id} introuvable"}
    _log_decision("validations", {"claim_id": claim_id, "verdict": verdict})
    new_label = "fraud" if verdict == "fraud_confirmed" else "legit"
    claims.loc[claims["claim_id"] == claim_id, "label"] = new_label
    collection.update(ids=[claim_id], metadatas=[{"label": new_label, "status": "confirmed"}])
    return {"status": "validated", "claim_id": claim_id, "verdict": verdict,
            "note": "ré-indexé comme exemple étiqueté pour les analyses futures"}


if __name__ == "__main__":
    # stdio : le backend (app/main.py) spawn ce processus et parle sur stdin/stdout.
    mcp_server.run()
