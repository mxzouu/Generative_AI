"""Serveur MCP « crédit » (transport stdio) — la boîte à outils de l'agent (les 6 tools).

Calqué sur projet/agent-detection-fraude/app/fraud_server.py : FastMCP + accès exclusif aux
données (SQLite credit_copilot.db, modèle XGBoost, index ChromaDB de la doc interne).

Garde-fous : run_credit_score / explain_score PROPOSENT ; seul record_decision — appelé sur
ordre explicite du conseiller — écrit une décision. Aucune décision de crédit automatique.

Prérequis : scripts/*.py + ml/train.py exécutés (DB, modèle, index présents).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import chromadb
from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

logging.getLogger("mcp").setLevel(logging.WARNING)

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
from ml.context import ctx_from_demande  # noqa: E402
from ml.features import TAUX_PAR_TYPE, feature_vector, mensualite  # noqa: E402
from ml.model import CreditModel  # noqa: E402

TYPES_CREDIT = ("immo", "conso", "auto", "renouvelable")
CONTRATS = ("CDI", "CDD", "indépendant", "sans emploi")

DB_PATH = PROJECT / "data" / "credit_copilot.db"
MODEL_PATH = PROJECT / "models" / "credit_model.joblib"
CHROMA_PATH = PROJECT / "chroma_index"
COLLECTION = "internal_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"
DECISIONS = ("accord", "refus", "analyse_manuelle", "escalade")
# Décisions qui ne clôturent PAS le dossier : il passe « en cours » (suivi), pas « traité ».
EN_COURS_DECISIONS = {"analyse_manuelle", "escalade", "contre_offre"}

# --- état partagé (chargé une fois au démarrage du sous-processus) ------------
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
model = CreditModel.load(MODEL_PATH)
embedder = SentenceTransformer(EMBED_MODEL)
collection = chromadb.PersistentClient(path=str(CHROMA_PATH)).get_collection(COLLECTION)

mcp_server = FastMCP("credit")


@mcp_server.tool()
def get_client_profile(client_id: str) -> dict:
    """Récupère le dossier client (identité, revenus, contrat, ancienneté) depuis la BDD."""
    row = conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
    return dict(row) if row else {"error": f"client {client_id} introuvable"}


@mcp_server.tool()
def run_credit_score(demande_id: str) -> dict:
    """Calcule le score de risque ML d'un dossier de la pile : proba de défaut + bande + reco.

    Renvoie { probability_default, decision_band, recommandation, no_auto_processing }.
    Si no_auto_processing=true (risque critique), aucun traitement automatique : escalade requise.
    C'est une PROPOSITION d'aide à la décision, pas une décision.
    """
    try:
        res = model.score(feature_vector(ctx_from_demande(conn, demande_id)))
    except ValueError as e:
        return {"error": str(e)}
    return {"demande_id": demande_id, **{k: res[k] for k in
            ("probability_default", "decision_band", "recommandation", "no_auto_processing")}}


@mcp_server.tool()
def explain_score(demande_id: str, top_n: int = 5) -> dict:
    """Justifie le score d'un dossier : top facteurs SHAP de CETTE prédiction (lisibles).

    Chaque facteur indique sa valeur, sa contribution et s'il augmente ou diminue le risque.
    """
    try:
        vec = feature_vector(ctx_from_demande(conn, demande_id))
    except ValueError as e:
        return {"error": str(e)}
    return {"demande_id": demande_id, "top_factors": model.explain(vec, top_n=top_n)}


@mcp_server.tool()
def search_internal_docs(query: str, k: int = 4) -> list:
    """RAG sur la doc interne (politique, grille de risque, procédures) AVEC citation (source + page).

    Utilise ce tool pour toute question réglementaire, et cite systématiquement (fichier.pdf, p.N).
    """
    q_vec = embedder.encode(query).tolist()
    res = collection.query(query_embeddings=[q_vec], n_results=k)
    return [
        {"source": m["source"], "page": m["page"], "extrait": doc,
         "distance": round(float(dist), 3)}
        for doc, dist, m in zip(res["documents"][0], res["distances"][0], res["metadatas"][0])
    ]


def _simulate(demande_id: str, montant: float | None = None, duree_mois: int | None = None,
              apport: float | None = None, valeur_garantie: float | None = None) -> dict:
    """Coeur du what-if : re-score un dossier avec des paramètres modifiés, SANS rien écrire.

    `apport` réduit le montant financé (montant_finance = montant_demande - apport).
    Renvoie l'état AVANT (conditions actuelles) et APRÈS (conditions modifiées).
    """
    d = conn.execute("SELECT * FROM demandes WHERE demande_id = ?", (demande_id,)).fetchone()
    if d is None:
        raise ValueError(f"dossier {demande_id} introuvable")
    base_ctx = ctx_from_demande(conn, demande_id)
    avant = model.score(feature_vector(base_ctx))

    type_credit = d["type_credit"]
    apport = float(apport or 0.0)
    montant_dem = float(montant) if montant is not None else float(d["montant_demande"])
    montant_finance = max(montant_dem - apport, 1.0)
    duree = int(duree_mois) if duree_mois is not None else int(d["duree_mois"])
    taux = TAUX_PAR_TYPE.get(type_credit, 0.06)
    mens = mensualite(montant_finance, taux, duree)
    val_gar = float(valeur_garantie) if valeur_garantie is not None else float(d["valeur_garantie_proposee"])

    ctx = dict(base_ctx)
    ctx["montant_demande"] = montant_finance
    ctx["duree_mois"] = duree
    ctx["mensualite_dossier"] = mens
    ctx["valeur_garantie"] = val_gar
    apres = model.score(feature_vector(ctx))

    keys = ("probability_default", "decision_band", "no_auto_processing")
    return {
        "demande_id": demande_id, "type_credit": type_credit,
        "params": {"montant_demande": round(montant_dem, 2), "apport": round(apport, 2),
                   "montant_finance": round(montant_finance, 2), "duree_mois": duree,
                   "valeur_garantie": round(val_gar, 2), "mensualite_estimee": mens},
        "avant": {k: avant[k] for k in keys},
        "apres": {k: apres[k] for k in keys},
    }


@mcp_server.tool()
def simulate_offer(demande_id: str, montant: float | None = None, duree_mois: int | None = None,
                   apport: float | None = None, valeur_garantie: float | None = None) -> dict:
    """WHAT-IF : re-calcule le score d'un dossier avec des conditions modifiées, SANS rien écrire.

    Sert à chercher une CONTRE-OFFRE acceptable : fais varier les leviers (apport pour baisser le
    montant financé, durée, garantie) et observe l'effet sur la probabilité de défaut. Chaque appel
    renvoie l'état AVANT et APRÈS (proba, bande de risque, mensualité). Itère jusqu'à sortir de la
    zone de refus/critique, puis fige la reco avec propose_counter_offer.
    """
    try:
        return _simulate(demande_id, montant, duree_mois, apport, valeur_garantie)
    except ValueError as e:
        return {"error": str(e)}


@mcp_server.tool()
def propose_counter_offer(demande_id: str, montant: float, duree_mois: int, apport: float = 0.0,
                          valeur_garantie: float | None = None, justification: str = "") -> dict:
    """Fige la CONTRE-OFFRE recommandée au conseiller (ne l'envoie pas, n'écrit rien en base).

    Recalcule le score de façon autoritative à partir des paramètres retenus et renvoie la
    proposition structurée que l'interface présentera au conseiller pour validation.
    N'appelle ce tool QU'UNE FOIS, à la fin, quand tu as trouvé des conditions acceptables.
    """
    try:
        sim = _simulate(demande_id, montant=montant, duree_mois=duree_mois,
                        apport=apport, valeur_garantie=valeur_garantie)
    except ValueError as e:
        return {"error": str(e)}
    return {"proposition_contre_offre": True, "justification": justification, **sim}


@mcp_server.tool()
def query_client_history(client_id: str) -> dict:
    """Historique du client : crédits passés/en cours, incidents de paiement, garanties."""
    credits = [dict(r) for r in conn.execute(
        "SELECT credit_id, type_credit, montant, duree_mois, statut, mensualite, date_debut "
        "FROM credits_historiques WHERE client_id = ? ORDER BY date_debut", (client_id,))]
    incidents = [dict(r) for r in conn.execute(
        "SELECT incident_id, credit_id, date_incident, type, montant_impaye, nb_jours_retard, "
        "regularise FROM incidents WHERE client_id = ? ORDER BY date_incident", (client_id,))]
    garanties = [dict(r) for r in conn.execute(
        "SELECT garantie_id, credit_id, type, valeur_estimee, statut FROM garanties "
        "WHERE client_id = ?", (client_id,))]
    return {"client_id": client_id, "credits": credits, "incidents": incidents,
            "garanties": garanties, "nb_credits_en_cours": sum(c["statut"] == "en cours" for c in credits)}


@mcp_server.tool()
def record_decision(client_id: str, demande_id: str, decision: str,
                    commentaire: str = "", conseiller_id: str = "conseiller_demo",
                    score_ml: float | None = None, tools_utilises: str = "") -> dict:
    """Enregistre la décision du CONSEILLER (accord/refus/analyse_manuelle/escalade) -> nourrit la base.

    À n'appeler QUE lorsque le conseiller a explicitement tranché (human-in-the-loop).
    Marque la demande comme traitée et journalise la décision (piste d'audit).
    """
    if decision not in DECISIONS:
        return {"error": f"decision doit être l'une de {DECISIONS}"}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # analyse manuelle / escalade : le dossier n'est pas clos -> il part « en cours ».
    statut = "en cours" if decision in EN_COURS_DECISIONS else "traité"
    conn.execute(
        "INSERT INTO decisions (client_id, demande_id, date_decision, conseiller_id, decision, "
        "score_ml, commentaire, tools_utilises) VALUES (?,?,?,?,?,?,?,?)",
        (client_id, demande_id, now, conseiller_id, decision, score_ml, commentaire, tools_utilises))
    conn.execute("UPDATE demandes SET statut = ? WHERE demande_id = ?", (statut, demande_id))
    conn.commit()
    return {"status": "enregistré", "demande_id": demande_id, "decision": decision,
            "statut": statut, "at": now}


def _next_id(prefix: str, table: str, col: str, width: int) -> str:
    row = conn.execute(f"SELECT {col} FROM {table} WHERE {col} LIKE ? ORDER BY {col} DESC LIMIT 1",
                       (prefix + "%",)).fetchone()
    n = (int(row[col][len(prefix):]) + 1) if row else 1
    return f"{prefix}{n:0{width}d}"


@mcp_server.tool()
def add_client(nom: str, prenom: str, age: int, revenu_mensuel_net: float,
               anciennete_emploi_mois: int, type_contrat: str,
               categorie_socio_pro: str = "employé", situation_familiale: str = "célibataire") -> dict:
    """Crée un NOUVEAU client dans la base et renvoie son client_id.

    type_contrat ∈ {CDI, CDD, indépendant, sans emploi}. Recueille ces informations auprès
    du conseiller avant d'appeler ce tool. Un nouveau client n'a ni historique ni incident.
    """
    if type_contrat not in CONTRATS:
        return {"error": f"type_contrat doit être l'un de {CONTRATS}"}
    cid = _next_id("CLI", "clients", "client_id", 5)
    naissance = date.fromordinal(date.today().toordinal() - int(age) * 365)
    conn.execute(
        "INSERT INTO clients (client_id, nom, prenom, date_naissance, age, situation_familiale, "
        "profession, categorie_socio_pro, revenu_mensuel_net, anciennete_emploi_mois, type_contrat, "
        "adresse, code_postal, date_creation_compte) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, nom, prenom, naissance.isoformat(), int(age), situation_familiale, categorie_socio_pro,
         categorie_socio_pro, float(revenu_mensuel_net), int(anciennete_emploi_mois), type_contrat,
         "—", "00000", date.today().isoformat()))
    conn.commit()
    return {"status": "client créé", "client_id": cid, "nom": nom, "prenom": prenom}


@mcp_server.tool()
def add_dossier(client_id: str, type_credit: str, montant_demande: float, duree_mois: int) -> dict:
    """Crée un NOUVEAU dossier (demande de crédit) pour un client EXISTANT, dans la pile « à traiter ».

    type_credit ∈ {immo, conso, auto, renouvelable}. Renvoie le demande_id créé. Après création,
    tu peux proposer au conseiller de scorer le dossier avec run_credit_score.
    """
    if type_credit not in TYPES_CREDIT:
        return {"error": f"type_credit doit être l'un de {TYPES_CREDIT}"}
    if conn.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,)).fetchone() is None:
        return {"error": f"client {client_id} introuvable"}
    did = _next_id("DOS", "demandes", "demande_id", 4)
    taux = TAUX_PAR_TYPE[type_credit]
    mens = mensualite(float(montant_demande), taux, int(duree_mois))
    val_gar = round(float(montant_demande) * 1.0, 2) if type_credit in ("immo", "auto") else 0.0
    conn.execute(
        "INSERT INTO demandes (demande_id, client_id, type_credit, montant_demande, duree_mois, taux, "
        "mensualite_estimee, valeur_garantie_proposee, date_demande, statut) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (did, client_id, type_credit, float(montant_demande), int(duree_mois), taux, mens, val_gar,
         date.today().isoformat(), "à traiter"))
    conn.commit()
    return {"status": "dossier créé", "demande_id": did, "client_id": client_id,
            "type_credit": type_credit, "montant_demande": float(montant_demande)}


@mcp_server.tool()
def reopen_dossier(demande_id: str) -> dict:
    """Réouvre un dossier déjà traité (ex. un refus) : le remet dans « à traiter » pour un réexamen.

    Supprime la décision précédente et repasse le dossier en attente. Renvoie le demande_id
    pour que l'interface puisse l'ouvrir directement.
    """
    if conn.execute("SELECT 1 FROM demandes WHERE demande_id = ?", (demande_id,)).fetchone() is None:
        return {"error": f"dossier {demande_id} introuvable"}
    conn.execute("DELETE FROM decisions WHERE demande_id = ?", (demande_id,))
    conn.execute("UPDATE demandes SET statut = 'à traiter' WHERE demande_id = ?", (demande_id,))
    conn.commit()
    return {"status": "réouvert", "demande_id": demande_id,
            "note": "remis dans la pile à traiter pour réexamen"}


@mcp_server.tool()
def list_dossiers(statut: str = "à traiter") -> list:
    """Liste les dossiers par statut : 'à traiter' ou 'traité' (avec la décision prise le cas échéant).

    Utile pour retrouver un dossier refusé à rouvrir (statut='traité', decision='refus').
    """
    if statut == "traité":
        rows = conn.execute(
            "SELECT dm.demande_id, dm.client_id, c.prenom, c.nom, dm.type_credit, dm.montant_demande, "
            "de.decision FROM demandes dm JOIN clients c ON c.client_id = dm.client_id "
            "LEFT JOIN decisions de ON de.demande_id = dm.demande_id "
            "WHERE dm.statut = 'traité' ORDER BY dm.demande_id").fetchall()
    else:
        rows = conn.execute(
            "SELECT dm.demande_id, dm.client_id, c.prenom, c.nom, dm.type_credit, dm.montant_demande "
            "FROM demandes dm JOIN clients c ON c.client_id = dm.client_id "
            "WHERE dm.statut = 'à traiter' ORDER BY dm.demande_id").fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    mcp_server.run()
