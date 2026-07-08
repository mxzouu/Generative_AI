"""Credit Copilot — interface conseiller (Streamlit).

Deux onglets : dossiers À TRAITER (tuiles cliquables, vue par défaut) et dossiers TRAITÉS
(liste avec statut). Cliquer une tuile ouvre le dossier : profil + score + explication
vulgarisée (table, sans jargon ML) + historique. Un chatbot flottant (logo en bas à droite)
répond aux questions réglementaires EN CONNAISSANT le dossier ouvert, et affiche directement
la/les page(s) de PDF citée(s).

Archi : l'affichage du score/explication et l'écriture des décisions passent en DIRECT par la
couche données (rapide, pas d'API) ; seul le chatbot mobilise l'agent LLM (via AgentBridge).

Lancer :  streamlit run streamlit_app.py   (depuis projet/agent-credit-copilot/)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st

from app.bridge import AgentBridge
from app.mailer import draft_email, send_email
from ml.context import ctx_from_demande
from ml.features import feature_vector
from ml.model import CreditModel

PROJECT = Path(__file__).resolve().parent
DB_PATH = PROJECT / "data" / "credit_copilot.db"
MODEL_PATH = PROJECT / "models" / "credit_model.joblib"
DOCS_DIR = PROJECT / "data" / "docs"

BADGES = {"accord": ("✅", "Accepté"), "refus": ("❌", "Refusé"),
          "analyse_manuelle": ("🔎", "Analyse manuelle"), "escalade": ("⬆️", "Escaladé"),
          "contre_offre": ("✉️", "Contre-offre envoyée")}
# Décisions qui laissent le dossier « en cours » (suivi) plutôt que de le clore en « traité ».
EN_COURS_DECISIONS = {"analyse_manuelle", "escalade", "contre_offre"}
CONTRAT = {0: "CDI", 1: "Indépendant", 2: "CDD", 3: "Sans emploi"}

st.set_page_config(page_title="Credit Copilot", page_icon="💳", layout="wide")
st.markdown("""
<style>
/* tuiles de dossiers : boutons hauts, alignés à gauche, texte multi-lignes */
.st-key-pile button { min-height: 120px; white-space: pre-wrap; text-align: left;
    align-items: flex-start; justify-content: flex-start; font-size: 0.9rem; line-height: 1.4; }
/* chatbot flottant en bas à droite */
.st-key-floatchat { position: fixed; bottom: 24px; right: 24px; left: auto;
    width: fit-content; z-index: 9999; }
.st-key-floatchat button { border-radius: 50%; height: 58px; width: 58px; font-size: 1.6rem; }
</style>
""", unsafe_allow_html=True)


# --- ressources --------------------------------------------------------------
@st.cache_resource
def get_model() -> CreditModel:
    return CreditModel.load(MODEL_PATH)


@st.cache_resource
def get_bridge() -> AgentBridge:
    return AgentBridge()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(show_spinner=False)
def score_dossier(demande_id: str) -> dict:
    conn = db()
    res = get_model().score(feature_vector(ctx_from_demande(conn, demande_id)))
    conn.close()
    return res


@st.cache_data(show_spinner=False)
def render_page(source: str, page: int) -> bytes:
    """Rend une page de PDF (1-indexée) en PNG pour l'afficher dans le chat."""
    doc = fitz.open(str(DOCS_DIR / source))
    pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2))  # zoom x2 pour la lisibilité
    return pix.tobytes("png")


def risk_emoji(p: float) -> str:
    return "🔴" if p >= 0.60 else ("🟠" if p >= 0.30 else "🟢")


def _json_values(text: str) -> list:
    """Décode un texte contenant un tableau JSON OU plusieurs objets JSON concaténés.

    FastMCP renvoie une liste comme N blocs de texte joints par '\\n' -> ce n'est pas un
    tableau JSON valide. On lit donc les valeurs une à une, puis on aplatit les listes.
    """
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


def pages_from_trace(trace: list[dict]) -> list[tuple]:
    """Extrait les (source, page) cités par search_internal_docs, dédupliqués."""
    pages, seen = [], set()
    for t in trace:
        if t["tool"] != "search_internal_docs":
            continue
        for hit in _json_values(t["output"]):
            if isinstance(hit, dict) and "source" in hit and "page" in hit:
                key = (hit["source"], hit["page"])
                if key not in seen:
                    seen.add(key)
                    pages.append(key)
    return pages


def fmt(feature: str, val: float) -> str:
    """Formate une valeur de feature en langage non technique."""
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
    if feature == "nb_incidents_12_mois":
        return f"{int(val)} incident(s)"
    if feature == "nb_jours_retard_max":
        return f"{int(val)} jours"
    if feature == "nb_credits_en_cours":
        return f"{int(val)}"
    if feature == "ratio_garantie_montant":
        return f"{val*100:.0f} % du montant"
    return str(val)


def enregistrer_decision(client_id, demande_id, decision, commentaire, score_ml):
    """Miroir du tool record_decision (écriture directe pour la fiabilité de la démo).

    analyse manuelle / escalade / contre-offre -> le dossier n'est pas clos : il passe « en cours ».
    accord / refus -> le dossier est clos : il passe « traité ».
    """
    statut = "en cours" if decision in EN_COURS_DECISIONS else "traité"
    conn = db()
    conn.execute(
        "INSERT INTO decisions (client_id, demande_id, date_decision, conseiller_id, decision, "
        "score_ml, commentaire, tools_utilises) VALUES (?,?,?,?,?,?,?,?)",
        (client_id, demande_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "conseiller_demo", decision, score_ml, commentaire, "UI"))
    conn.execute("UPDATE demandes SET statut = ? WHERE demande_id = ?", (statut, demande_id))
    conn.commit()
    conn.close()


def offer_from_trace(trace: list[dict]) -> dict | None:
    """Extrait la contre-offre figée par propose_counter_offer dans la trace de l'agent."""
    for t in reversed(trace):
        if t.get("tool") != "propose_counter_offer":
            continue
        for obj in _json_values(t["output"]):
            if isinstance(obj, dict) and obj.get("proposition_contre_offre"):
                return obj
    return None


# Libellés lisibles des outils, pour donner à voir le raisonnement de l'agent (« comme Claude Code »).
TOOL_LABELS = {
    "get_client_profile": "Consulte le profil du client",
    "run_credit_score": "Calcule le score de risque",
    "explain_score": "Analyse les facteurs du score",
    "simulate_offer": "Teste une variante d'offre (what-if)",
    "propose_counter_offer": "Fige la contre-offre recommandée",
    "search_internal_docs": "Cherche dans la doc réglementaire",
    "query_client_history": "Consulte l'historique du client",
    "record_decision": "Enregistre la décision",
}


def steps_from_trace(trace: list[dict]) -> list[tuple]:
    """Transforme la trace (pensées + tool calls) en étapes lisibles à afficher sous la réponse."""
    steps = []
    for t in trace:
        if t.get("tool") == "_thought":
            steps.append(("💭", t.get("text", "")))
        else:
            steps.append(("🔧", TOOL_LABELS.get(t.get("tool"), t.get("tool", ""))))
    return steps


if "selected" not in st.session_state:
    st.session_state.selected = None
if "chats" not in st.session_state:
    st.session_state.chats = {}
if "offer_flow" not in st.session_state:
    st.session_state.offer_flow = {}  # demande_id -> {stage, offer, email}


# ============================================================================
# VUE 1 — les trois onglets (aucun dossier ouvert)
# ============================================================================
def dossiers_by_statut(statut: str) -> list:
    """Dossiers d'un statut donné, avec leur dernière décision (le cas échéant)."""
    conn = db()
    rows = conn.execute(
        "SELECT dm.demande_id, dm.client_id, dm.type_credit, dm.montant_demande, c.prenom, c.nom, "
        "de.decision, de.date_decision, de.commentaire "
        "FROM demandes dm JOIN clients c ON c.client_id = dm.client_id "
        "LEFT JOIN decisions de ON de.demande_id = dm.demande_id AND de.date_decision = "
        "(SELECT MAX(date_decision) FROM decisions WHERE demande_id = dm.demande_id) "
        "WHERE dm.statut = ? ORDER BY dm.demande_id", (statut,)).fetchall()
    conn.close()
    return rows


def render_pile():
    """Onglet « à traiter » : tuiles cliquables colorées par le niveau de risque."""
    pile = dossiers_by_statut("à traiter")
    if not pile:
        st.success("Aucun dossier à traiter 🎉")
        return
    st.caption(f"{len(pile)} dossiers en attente — clique une tuile pour l'instruire.")
    with st.container(key="pile"):
        cols = st.columns(3)
        for i, r in enumerate(pile):
            p = score_dossier(r["demande_id"])["probability_default"]
            label = (f"{risk_emoji(p)} {r['demande_id']}\n"
                     f"{r['prenom']} {r['nom']}\n"
                     f"{r['type_credit']} · {r['montant_demande']:,.0f} €".replace(",", " "))
            if cols[i % 3].button(label, key=f"tile_{r['demande_id']}", use_container_width=True):
                st.session_state.selected = r["demande_id"]
                st.rerun()


def render_statut_list(statut: str, empty_msg: str):
    """Onglet « en cours » / « traités » : liste des dossiers avec badge de décision."""
    rows = dossiers_by_statut(statut)
    if not rows:
        st.info(empty_msg)
        return
    for r in rows:
        emoji, libelle = BADGES.get(r["decision"], ("•", r["decision"] or "—"))
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.markdown(f"**{r['demande_id']} — {r['prenom']} {r['nom']}**  \n"
                        f"{r['type_credit']} · {r['montant_demande']:,.0f} €".replace(",", " "))
            c2.markdown(f"### {emoji} {libelle}")
            if c3.button("Voir", key=f"see_{statut}_{r['demande_id']}"):
                st.session_state.selected = r["demande_id"]
                st.rerun()
            if r["commentaire"]:
                st.caption(f"📝 {r['commentaire']}")


def render_lists():
    st.title("💳 Credit Copilot")
    tab_pile, tab_encours, tab_traites = st.tabs(
        ["📥 Dossiers à traiter", "⏳ En cours", "✅ Dossiers traités"])
    with tab_pile:
        render_pile()
    with tab_encours:
        render_statut_list("en cours", "Aucun dossier en cours de suivi.")
    with tab_traites:
        render_statut_list("traité", "Aucun dossier traité pour l'instant.")


# ============================================================================
# VUE 2 — détail d'un dossier ouvert
# ============================================================================
def render_detail(demande_id: str):
    conn = db()
    row = conn.execute("SELECT * FROM demandes WHERE demande_id = ?", (demande_id,)).fetchone()
    client = conn.execute("SELECT * FROM clients WHERE client_id = ?", (row["client_id"],)).fetchone()
    deja = conn.execute("SELECT * FROM decisions WHERE demande_id = ? ORDER BY date_decision DESC LIMIT 1",
                        (demande_id,)).fetchone()

    if st.button("← Retour à la pile"):
        st.session_state.selected = None
        st.rerun()

    score = score_dossier(demande_id)
    vec = feature_vector(ctx_from_demande(conn, demande_id))

    st.title(f"Dossier {demande_id} — {client['prenom']} {client['nom']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Probabilité de défaut", f"{score['probability_default']*100:.1f} %")
    c2.metric("Niveau de risque", score["decision_band"])
    c3.metric("Recommandation", score["recommandation"])
    if score["no_auto_processing"]:
        st.error("⛔ Risque critique — pas de traitement automatique. Escalade obligatoire.")

    col_profil, col_expl = st.columns(2)
    with col_profil:
        st.subheader("👤 Profil client")
        profil = {
            "Âge": f"{client['age']} ans", "Catégorie": client["categorie_socio_pro"],
            "Revenu net mensuel": f"{client['revenu_mensuel_net']:,.0f} €".replace(",", " "),
            "Contrat": client["type_contrat"],
            "Ancienneté emploi": f"{client['anciennete_emploi_mois']} mois",
            "Situation familiale": client["situation_familiale"],
            "Crédit demandé": f"{row['type_credit']} — {row['montant_demande']:,.0f} € sur {row['duree_mois']} mois".replace(",", " "),
        }
        st.dataframe(pd.DataFrame(profil.items(), columns=["Information", "Valeur"]),
                     hide_index=True, use_container_width=True)
    with col_expl:
        st.subheader("📊 Pourquoi ce score ?")
        factors = get_model().explain(vec, top_n=6)
        top = factors[0]
        sens = "pénalisé" if top["contribution"] > 0 else "favorisé"
        st.info(f"En clair : ce dossier est surtout **{sens}** par « {top['facteur'].lower()} ».")
        table = pd.DataFrame([{
            "Facteur": f["facteur"],
            "Situation du client": fmt(f["feature"], f["valeur"]),
            "Effet sur le risque": "⬆️ Augmente" if f["contribution"] > 0 else "⬇️ Diminue",
        } for f in factors])
        st.dataframe(table, hide_index=True, use_container_width=True)
        st.caption("Facteurs classés du plus au moins influent sur la décision.")

    with st.expander("📚 Historique du client (crédits · incidents · garanties)"):
        for titre, q in {
            "Crédits": "SELECT type_credit, montant, statut, mensualite FROM credits_historiques WHERE client_id=?",
            "Incidents": "SELECT date_incident, type, nb_jours_retard, regularise FROM incidents WHERE client_id=?",
            "Garanties": "SELECT type, valeur_estimee, statut FROM garanties WHERE client_id=?",
        }.items():
            st.markdown(f"**{titre}**")
            st.dataframe(pd.DataFrame([dict(x) for x in conn.execute(q, (row["client_id"],))]),
                         hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("✅ Décision du conseiller")
    if deja:
        emoji, libelle = BADGES.get(deja["decision"], ("•", deja["decision"]))
        st.success(f"Dossier déjà traité : {emoji} **{libelle}** — {deja['date_decision'][:10]}")
        if deja["commentaire"]:
            st.caption(f"📝 {deja['commentaire']}")
    else:
        commentaire = st.text_area("Motivation", placeholder="Justification de la décision…")
        b1, b2, b3, b4 = st.columns(4)
        for col, code, label in [(b1, "accord", "Accorder"), (b2, "analyse_manuelle", "Analyse manuelle"),
                                 (b3, "refus", "Refuser"), (b4, "escalade", "Escalader")]:
            if col.button(label, use_container_width=True, key=f"dec_{code}"):
                enregistrer_decision(row["client_id"], demande_id, code, commentaire,
                                     score["probability_default"])
                st.success(f"Décision « {label} » enregistrée.")
                st.rerun()

    # Workflow de contre-offre (déclenché depuis le chat) : panneau persistant sur la page.
    render_offer_flow(demande_id, client, row)

    conn.close()
    render_floating_chat(demande_id, client, row, score)


# ============================================================================
# Workflow de contre-offre (dans le chat) : proposition -> mail -> envoi -> « en cours »
# ============================================================================
def _euro(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


def render_offer_flow(demande_id, client, row):
    """Affiche l'étape courante du workflow de contre-offre pour le dossier ouvert.

    Étapes : 'proposed' (l'agent a proposé une offre -> le conseiller valide)
             -> 'email' (l'agent a rédigé le mail -> le conseiller relit et envoie)
             -> envoi : dossier basculé « en cours ».
    """
    flow = st.session_state.offer_flow.get(demande_id)
    if not flow:
        return
    offer = flow["offer"]
    p, av, ap = offer["params"], offer["avant"], offer["apres"]

    if flow["stage"] == "proposed":
        st.divider()
        st.markdown("**📝 Contre-offre proposée par l'agent**")
        st.markdown(
            f"- Montant : {_euro(p['montant_demande'])} → financé **{_euro(p['montant_finance'])}** "
            f"(apport {_euro(p['apport'])})\n"
            f"- Durée : **{p['duree_mois']} mois** · mensualité estimée ~{_euro(p['mensualite_estimee'])}\n"
            f"- Garantie : {_euro(p['valeur_garantie'])}\n"
            f"- Risque : {av['probability_default']*100:.0f} % ({av['decision_band']}) → "
            f"**{ap['probability_default']*100:.0f} % ({ap['decision_band']})**")
        if offer.get("justification"):
            st.caption(offer["justification"])
        c1, c2 = st.columns(2)
        if c1.button("✅ Valider et rédiger le mail", key=f"valid_offer_{demande_id}",
                     use_container_width=True):
            ctx_mail = (
                f"Client : {client['prenom']} {client['nom']}. "
                f"Demande initiale : {row['type_credit']} de {_euro(row['montant_demande'])} "
                f"sur {row['duree_mois']} mois. "
                f"Contre-offre proposée : montant financé {_euro(p['montant_finance'])} "
                f"(apport {_euro(p['apport'])}), durée {p['duree_mois']} mois, "
                f"mensualité estimée {_euro(p['mensualite_estimee'])}.")
            with st.spinner("L'agent rédige le courrier au client…"):
                flow["email"] = draft_email("contre_offre", ctx_mail, demande_id)
            flow["stage"] = "email"
            st.rerun()
        if c2.button("✖️ Abandonner", key=f"drop_offer_{demande_id}", use_container_width=True):
            st.session_state.offer_flow.pop(demande_id, None)
            st.rerun()

    elif flow["stage"] == "email":
        st.divider()
        st.markdown("**✉️ Courrier au client — à relire avant envoi**")
        email = flow["email"]
        subj = st.text_input("Objet", value=email["subject"], key=f"subj_{demande_id}")
        body = st.text_area("Corps du message", value=email["body"], height=220,
                            key=f"body_{demande_id}")
        st.caption(f"Destinataire : {email['to']}")
        c1, c2 = st.columns(2)
        if c1.button("📤 Envoyer au client", key=f"send_offer_{demande_id}", use_container_width=True):
            with st.spinner("Envoi en cours…"):
                res = send_email(email["to"], subj, body)
            enregistrer_decision(
                client["client_id"], demande_id, "contre_offre",
                f"Contre-offre envoyée : {_euro(p['montant_finance'])} sur {p['duree_mois']} mois "
                f"(apport {_euro(p['apport'])}). Risque ramené à "
                f"{ap['probability_default']*100:.0f} % ({ap['decision_band']}).",
                ap["probability_default"])
            st.session_state.offer_flow.pop(demande_id, None)
            st.success("Courrier envoyé — dossier déplacé dans « En cours ». "
                       + res.get("detail", ""))
            st.rerun()
        if c2.button("✖️ Annuler", key=f"cancel_mail_{demande_id}", use_container_width=True):
            st.session_state.offer_flow.pop(demande_id, None)
            st.rerun()


# ============================================================================
# Chatbot flottant (logo bas-droite -> panneau) avec contexte du dossier
# ============================================================================
def render_floating_chat(demande_id, client, row, score):
    ctx = (f"Dossier {demande_id} — client {client['client_id']} ({client['prenom']} {client['nom']}). "
           f"Demande : {row['type_credit']} de {row['montant_demande']:.0f} € sur {row['duree_mois']} mois. "
           f"Score du modèle : probabilité de défaut {score['probability_default']*100:.0f} %, "
           f"bande '{score['decision_band']}', recommandation '{score['recommandation']}', "
           f"no_auto_processing={score['no_auto_processing']}. "
           f"Quand le conseiller dit « ce dossier » ou « ce client », il s'agit de {demande_id}.")
    chat = st.session_state.chats.setdefault(demande_id, [])

    with st.container(key="floatchat"):
        with st.popover("💬", use_container_width=False):
            st.markdown(f"**💬 Assistant réglementaire** · dossier {demande_id}")
            zone = st.container(height=360)
            with zone:
                for m in chat:
                    st.chat_message(m["role"]).write(m["content"])
                    if m.get("steps"):
                        with st.expander(f"🔍 Étapes de l'agent ({len(m['steps'])})"):
                            for icon, txt in m["steps"]:
                                st.markdown(f"{icon} {txt}")
                    for src, pg in m.get("pages", []):
                        with st.expander(f"📄 {src} — page {pg}"):
                            st.image(render_page(src, pg), use_container_width=True)
            with st.form(key=f"chatform_{demande_id}", clear_on_submit=True):
                q = st.text_input("Question", placeholder="Ex : ce dossier respecte-t-il la politique ?",
                                  label_visibility="collapsed")
                envoye = st.form_submit_button("Envoyer", use_container_width=True)
            if envoye and q:
                chat.append({"role": "user", "content": q})
                history = [{"role": m["role"], "content": m["content"]} for m in chat]
                with st.spinner("L'agent travaille…"):
                    reply, trace = get_bridge().ask(history, context=ctx)
                pages = pages_from_trace(trace)
                chat.append({"role": "assistant", "content": reply, "pages": pages[:3],
                             "steps": steps_from_trace(trace)})
                offer = offer_from_trace(trace)
                if offer and "error" not in offer:
                    st.session_state.offer_flow[demande_id] = {"stage": "proposed", "offer": offer}
                st.rerun()


# --- routeur -----------------------------------------------------------------
if st.session_state.selected:
    render_detail(st.session_state.selected)
else:
    render_lists()
