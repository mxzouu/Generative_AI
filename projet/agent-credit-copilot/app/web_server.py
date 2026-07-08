"""Credit Copilot — backend web (FastAPI).

Remplace l'UI Streamlit par une API REST + un frontend statique (web/, design Apple).
L'agent + MCP + ML + RAG sont inchangés : ce backend ouvre une session MCP stdio vers
credit_server.py (comme le projet fraude), sert les endpoints déterministes (dossiers, score,
explication, décision, pages PDF) en direct via la couche données, et l'endpoint /api/chat
via la boucle agent (Haiku).

Lancer :  uvicorn app.web_server:app --app-dir . --port 8600   (depuis projet/agent-credit-copilot/)
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

from .agent import PROJECT, REPO_ROOT, CreditAgent, server_params
from .mailer import draft_email, send_email
from ml.context import ctx_from_demande
from ml.features import FEATURE_LABELS, feature_vector
from ml.model import CreditModel

load_dotenv(PROJECT / ".env")
load_dotenv(REPO_ROOT / ".env")

DB_PATH = PROJECT / "data" / "credit_copilot.db"
MODEL_PATH = PROJECT / "models" / "credit_model.joblib"
DOCS_DIR = PROJECT / "data" / "docs"
WEB_DIR = PROJECT / "web"

DECISIONS = ("accord", "refus", "analyse_manuelle", "escalade")
KINDS = set(DECISIONS) | {"contre_offre"}  # types de courrier acceptés (décisions + contre-offre)
# Décisions/actions qui laissent le dossier « en cours » (suivi) au lieu de le clore en « traité ».
EN_COURS_DECISIONS = {"analyse_manuelle", "escalade", "contre_offre"}
DECISION_LABELS = {"accord": "Accepté", "refus": "Refusé",
                   "analyse_manuelle": "Analyse manuelle", "escalade": "Escaladé",
                   "contre_offre": "Contre-offre envoyée"}
CONTRAT = {0: "CDI", 1: "Indépendant", 2: "CDD", 3: "Sans emploi"}

model = CreditModel.load(MODEL_PATH)
_score_cache: dict[str, dict] = {}
state: dict = {"agent": None, "lock": asyncio.Lock()}


# --- helpers -----------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def risk_level(p: float) -> str:
    return "high" if p >= 0.60 else ("medium" if p >= 0.30 else "low")


def score_of(conn, demande_id: str) -> dict:
    if demande_id not in _score_cache:
        _score_cache[demande_id] = model.score(feature_vector(ctx_from_demande(conn, demande_id)))
    return _score_cache[demande_id]


def pretty(feature: str, val: float) -> str:
    if feature == "age":
        return f"{int(val)} ans"
    if feature in ("revenu_mensuel_net", "montant_demande"):
        return f"{val:,.0f} €".replace(",", " ")
    if feature == "anciennete_emploi_mois":
        return f"{int(val)} mois (~{val/12:.0f} ans)"
    if feature == "type_contrat_encoded":
        return CONTRAT.get(int(val), "?")
    if feature == "duree_mois":
        return f"{int(val)} mois"
    if feature == "taux_endettement":
        return f"{val*100:.0f} %"
    if feature == "nb_jours_retard_max":
        return f"{int(val)} jours"
    if feature == "ratio_garantie_montant":
        return f"{val*100:.0f} % du montant"
    return str(int(val)) if float(val).is_integer() else str(val)


def _json_values(text: str) -> list:
    """Décode un tableau JSON OU des objets JSON concaténés (format des tools MCP/FastMCP)."""
    dec, out, idx = json.JSONDecoder(), [], 0
    while idx < len(text):
        rest = text[idx:]
        stripped = rest.lstrip()
        idx += len(rest) - len(stripped)
        if not stripped:
            break
        try:
            obj, end = dec.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        out.extend(obj if isinstance(obj, list) else [obj])
        idx = end
    return out


def sources_from_trace(trace: list[dict]) -> list[dict]:
    seen, sources = set(), []
    for t in trace:
        if t["tool"] != "search_internal_docs":
            continue
        for hit in _json_values(t["output"]):
            if isinstance(hit, dict) and "source" in hit and "page" in hit:
                key = (hit["source"], hit["page"])
                if key not in seen:
                    seen.add(key)
                    sources.append({"source": hit["source"], "page": hit["page"]})
    return sources


def action_from_trace(trace: list[dict]) -> dict | None:
    """Détecte une action déclenchée par l'agent qui doit piloter l'UI (ouvrir/rafraîchir/contre-offre)."""
    action = None
    for t in trace:
        if "output" not in t:  # items de raisonnement (_thought) : pas de sortie d'outil
            continue
        for v in _json_values(t["output"]):
            if not isinstance(v, dict):
                continue
            if t["tool"] == "propose_counter_offer" and v.get("proposition_contre_offre"):
                action = {"type": "counter_offer", "offer": v}
            elif t["tool"] in ("add_dossier", "reopen_dossier") and v.get("demande_id"):
                action = {"type": "open_dossier", "demande_id": v["demande_id"]}
            elif t["tool"] == "add_client" and v.get("client_id"):
                action = action or {"type": "refresh"}
    return action


def offer_context(offer: dict) -> str:
    """Résumé texte de la contre-offre, injecté dans le contexte de rédaction du courrier."""
    p = offer.get("params", {})
    return (" CONTRE-OFFRE à présenter au client : "
            f"montant financé {p.get('montant_finance', 0):.0f} € "
            f"(apport {p.get('apport', 0):.0f} €), durée {p.get('duree_mois')} mois, "
            f"mensualité estimée {p.get('mensualite_estimee', 0):.0f} €.")


def build_context(demande_id: str | None) -> str:
    """Contexte texte d'un dossier ouvert (pour le chat et la rédaction d'emails)."""
    if not demande_id:
        return ""
    conn = db()
    d = conn.execute("SELECT * FROM demandes WHERE demande_id = ?", (demande_id,)).fetchone()
    if d is None:
        conn.close()
        return ""
    cl = conn.execute("SELECT * FROM clients WHERE client_id = ?", (d["client_id"],)).fetchone()
    s = score_of(conn, demande_id)
    conn.close()
    return (f"Dossier {demande_id} — client {d['client_id']} ({cl['prenom']} {cl['nom']}). "
            f"Demande : {d['type_credit']} de {d['montant_demande']:.0f} € sur {d['duree_mois']} mois. "
            f"Revenu net {cl['revenu_mensuel_net']:.0f} €, contrat {cl['type_contrat']}. "
            f"Score du modèle : probabilité de défaut {s['probability_default']*100:.0f} %, "
            f"bande '{s['decision_band']}', recommandation '{s['recommandation']}', "
            f"no_auto_processing={s['no_auto_processing']}. "
            f"Quand le conseiller dit « ce dossier » ou « ce client », il s'agit de {demande_id}.")


# --- cycle de vie : session MCP ouverte au démarrage -------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params()))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        agent = CreditAgent(session)
        await agent.discover_tools()
        state["agent"] = agent
        yield


app = FastAPI(title="Credit Copilot", lifespan=lifespan)


# --- modèles de requête ------------------------------------------------------
class ChatRequest(BaseModel):
    messages: list[dict]
    demande_id: str | None = None


class DecisionRequest(BaseModel):
    client_id: str
    demande_id: str
    decision: str
    commentaire: str = ""


class EmailDraftRequest(BaseModel):
    demande_id: str
    kind: str
    offer: dict | None = None  # contexte de la contre-offre (kind == "contre_offre")


class EmailSendRequest(BaseModel):
    demande_id: str
    client_id: str
    kind: str
    to: str
    subject: str
    body: str
    offer: dict | None = None


# --- endpoints ---------------------------------------------------------------
@app.get("/api/dossiers")
def dossiers():
    conn = db()
    a_traiter = []
    for r in conn.execute(
            "SELECT d.demande_id, d.client_id, d.type_credit, d.montant_demande, c.nom, c.prenom "
            "FROM demandes d JOIN clients c ON c.client_id = d.client_id "
            "WHERE d.statut = 'à traiter' ORDER BY d.demande_id"):
        p = score_of(conn, r["demande_id"])["probability_default"]
        a_traiter.append({**dict(r), "proba": p, "risk": risk_level(p)})

    def bucket(statut: str) -> list[dict]:
        """Dossiers d'un statut donné, avec leur dernière décision (pour le badge)."""
        rows = conn.execute(
            "SELECT dm.demande_id, dm.client_id, dm.type_credit, dm.montant_demande, c.nom, c.prenom, "
            "de.decision, de.date_decision, de.commentaire "
            "FROM demandes dm JOIN clients c ON c.client_id = dm.client_id "
            "LEFT JOIN decisions de ON de.demande_id = dm.demande_id AND de.date_decision = "
            "(SELECT MAX(date_decision) FROM decisions WHERE demande_id = dm.demande_id) "
            "WHERE dm.statut = ? ORDER BY dm.demande_id", (statut,)).fetchall()
        return [{**dict(r), "decision_label": DECISION_LABELS.get(r["decision"], r["decision"])}
                for r in rows]

    en_cours, traites = bucket("en cours"), bucket("traité")
    conn.close()
    return {"a_traiter": a_traiter, "en_cours": en_cours, "traites": traites}


@app.get("/api/dossier/{demande_id}")
def dossier(demande_id: str):
    conn = db()
    d = conn.execute("SELECT * FROM demandes WHERE demande_id = ?", (demande_id,)).fetchone()
    if d is None:
        conn.close()
        raise HTTPException(404, "dossier introuvable")
    client = conn.execute("SELECT * FROM clients WHERE client_id = ?", (d["client_id"],)).fetchone()
    score = score_of(conn, demande_id)
    vec = feature_vector(ctx_from_demande(conn, demande_id))
    factors = [{
        "facteur": f["facteur"], "feature": f["feature"],
        "valeur": pretty(f["feature"], f["valeur"]),
        "effet": "augmente" if f["contribution"] > 0 else "diminue",
    } for f in model.explain(vec, top_n=6)]

    hist = {
        "credits": [dict(x) for x in conn.execute(
            "SELECT type_credit, montant, statut, mensualite FROM credits_historiques WHERE client_id=?",
            (d["client_id"],))],
        "incidents": [dict(x) for x in conn.execute(
            "SELECT date_incident, type, nb_jours_retard, regularise FROM incidents WHERE client_id=?",
            (d["client_id"],))],
        "garanties": [dict(x) for x in conn.execute(
            "SELECT type, valeur_estimee, statut FROM garanties WHERE client_id=?", (d["client_id"],))],
    }
    deja = conn.execute("SELECT decision, date_decision, commentaire FROM decisions "
                        "WHERE demande_id = ? ORDER BY date_decision DESC LIMIT 1", (demande_id,)).fetchone()
    conn.close()
    return {
        "demande": dict(d), "client": dict(client),
        "score": {**score, "risk": risk_level(score["probability_default"])},
        "factors": factors, "history": hist,
        "decision": (dict(deja) | {"label": DECISION_LABELS.get(deja["decision"])}) if deja else None,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    agent = state["agent"]
    context = build_context(req.demande_id)
    async with state["lock"]:
        reply, trace = await agent.run(req.messages, context=context)
    _score_cache.clear()  # l'agent a pu créer/rouvrir un dossier -> on invalide le cache de scores
    return {"reply": reply, "sources": sources_from_trace(trace), "action": action_from_trace(trace)}


@app.post("/api/decision")
def decision(req: DecisionRequest):
    if req.decision not in DECISIONS:
        raise HTTPException(400, f"decision invalide (attendu : {DECISIONS})")
    statut = "en cours" if req.decision in EN_COURS_DECISIONS else "traité"
    conn = db()
    conn.execute(
        "INSERT INTO decisions (client_id, demande_id, date_decision, conseiller_id, decision, "
        "score_ml, commentaire, tools_utilises) VALUES (?,?,?,?,?,?,?,?)",
        (req.client_id, req.demande_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "conseiller_demo", req.decision,
         score_of(conn, req.demande_id)["probability_default"], req.commentaire, "web"))
    conn.execute("UPDATE demandes SET statut = ? WHERE demande_id = ?", (statut, req.demande_id))
    conn.commit()
    conn.close()
    return {"status": "enregistré", "decision": req.decision, "statut": statut}


@app.get("/api/pdf/{source}/{page}")
def pdf_page(source: str, page: int):
    path = DOCS_DIR / source
    if path.name != source or not path.exists():  # anti path-traversal
        raise HTTPException(404, "document introuvable")
    doc = fitz.open(str(path))
    if not (1 <= page <= doc.page_count):
        raise HTTPException(404, "page hors limites")
    png = doc[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    return Response(content=png, media_type="image/png")


@app.post("/api/draft-email")
def api_draft_email(req: EmailDraftRequest):
    """L'agent rédige le brouillon d'email correspondant à la décision (à relire/modifier par le conseiller)."""
    if req.kind not in KINDS:
        raise HTTPException(400, f"kind invalide (attendu : {KINDS})")
    ctx = build_context(req.demande_id)
    if not ctx:
        raise HTTPException(404, "dossier introuvable")
    if req.kind == "contre_offre" and req.offer:
        ctx += offer_context(req.offer)
    return draft_email(req.kind, ctx, req.demande_id)


@app.post("/api/send-email")
def api_send_email(req: EmailSendRequest):
    """Envoie l'email confirmé par le conseiller ET enregistre la décision (l'email finalise l'action).

    Contre-offre / analyse manuelle / escalade -> le dossier passe « en cours » (suivi).
    Accord / refus -> le dossier est clos (« traité »).
    """
    if req.kind not in KINDS:
        raise HTTPException(400, f"kind invalide (attendu : {KINDS})")
    result = send_email(req.to, req.subject, req.body)
    conn = db()
    etat = "envoyé" if result["sent"] else ("simulé" if result["simulated"] else "échec")
    statut = "en cours" if req.kind in EN_COURS_DECISIONS else "traité"
    commentaire = f"Email {etat} à {req.to} — {req.subject}"
    if req.kind == "contre_offre" and req.offer:
        p, ap = req.offer.get("params", {}), req.offer.get("apres", {})
        commentaire = (f"Contre-offre {etat} : {p.get('montant_finance', 0):.0f} € sur "
                       f"{p.get('duree_mois')} mois (apport {p.get('apport', 0):.0f} €). "
                       f"Risque ramené à {ap.get('probability_default', 0)*100:.0f} % "
                       f"({ap.get('decision_band')}).")
    conn.execute(
        "INSERT INTO decisions (client_id, demande_id, date_decision, conseiller_id, decision, "
        "score_ml, commentaire, tools_utilises) VALUES (?,?,?,?,?,?,?,?)",
        (req.client_id, req.demande_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "conseiller_demo", req.kind, score_of(conn, req.demande_id)["probability_default"],
         commentaire, "web+email"))
    conn.execute("UPDATE demandes SET statut = ? WHERE demande_id = ?", (statut, req.demande_id))
    conn.commit()
    conn.close()
    return {"email": result, "decision": req.kind, "statut": statut}


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
