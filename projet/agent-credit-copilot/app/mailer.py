"""Rédaction (Haiku) et envoi (SMTP) des emails du Credit Copilot.

Flux human-in-the-loop : l'agent RÉDIGE le brouillon (draft_email), le conseiller le relit /
modifie dans l'interface, puis CONFIRME → envoi (send_email). L'envoi n'est jamais automatique.

Envoi réel via SMTP Gmail : nécessite un mot de passe d'application dans .env (SMTP_APP_PASSWORD).
Sans ce mot de passe → mode « simulation » (rien n'est envoyé, l'email est journalisé dans
data/outbox.log). Adresses de test fixées ci-dessous.
"""
from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parent.parent
OUTBOX = PROJECT / "data" / "outbox.log"
load_dotenv(PROJECT / ".env")
load_dotenv(PROJECT.parent.parent / ".env")  # racine du repo

# --- adresses (TEST) ---------------------------------------------------------
# Expéditeur = SMTP_USER si défini dans .env, sinon l'adresse de test ci-dessous.
SENDER = os.getenv("SMTP_USER", "tomilshi20@gmail.com")
CLIENT_EMAIL = "tomilshi20@gmail.com"    # tous les clients pointent ici pour les tests
SUPERIOR_EMAIL = "aiteldjouditamazouzt@gmail.com"  # destinataire des escalades

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
if "@" in SMTP_HOST or "." not in SMTP_HOST:  # garde-fou : SMTP_HOST mal renseigné (ex. une adresse email)
    SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

MODEL = "claude-haiku-4-5"

SUBJECTS = {
    "accord": "Votre demande de crédit — Accord de principe",
    "refus": "Votre demande de crédit — Notre réponse",
    "analyse_manuelle": "Votre demande de crédit — Informations complémentaires",
    "contre_offre": "Votre demande de crédit — Une proposition adaptée",
}
CONSIGNES = {
    "accord": "Rédige un email chaleureux mais professionnel annonçant au client que sa demande de "
              "crédit reçoit un ACCORD de principe. Rappelle le type de crédit, le montant et la durée. "
              "Indique que les prochaines étapes (édition de l'offre, pièces) lui seront communiquées.",
    "refus": "Rédige un email courtois et respectueux annonçant au client que sa demande de crédit ne "
             "peut être acceptée en l'état. Reste factuel et bienveillant, sans détailler le score interne ; "
             "invite le client à recontacter son conseiller pour en discuter.",
    "analyse_manuelle": "Rédige un email demandant poliment au client des informations / pièces "
                        "complémentaires nécessaires à l'étude de son dossier (par ex. justificatifs de "
                        "revenus récents, relevés). Explique que son dossier fait l'objet d'un examen approfondi.",
    "contre_offre": "Rédige un email chaleureux et professionnel proposant au client une CONTRE-OFFRE : "
                    "suite à l'étude de sa demande, la banque propose de nouvelles conditions plus adaptées. "
                    "Présente clairement ces nouvelles conditions (montant financé, apport éventuel, durée, "
                    "mensualité estimée) telles qu'elles figurent dans le contexte, explique qu'elles visent à "
                    "rendre le financement soutenable, et invite le client à revenir vers son conseiller pour "
                    "accepter la proposition ou en discuter. N'évoque jamais le score interne.",
    "escalade": "Rédige un email INTERNE, adressé à un responsable des engagements, résumant la situation "
                "du dossier (numéro de dossier, client, montant, niveau de risque) et demandant un arbitrage. "
                "Ton professionnel, concis, orienté décision.",
}


def recipient(kind: str) -> str:
    return SUPERIOR_EMAIL if kind == "escalade" else CLIENT_EMAIL


def subject_for(kind: str, demande_id: str) -> str:
    if kind == "escalade":
        return f"Escalade dossier {demande_id} — demande d'arbitrage"
    return SUBJECTS.get(kind, "Votre demande de crédit")


def _parse_draft(raw: str) -> tuple[str, str]:
    """Sépare la réponse du modèle en (reasoning, body).

    Format attendu : 1re ligne « RAISONNEMENT: … », puis une ligne « --- », puis le corps.
    Robuste aux corps multi-lignes (contrairement au JSON) et tolérant si le format n'est pas suivi.
    """
    lines = raw.strip().split("\n")
    reasoning = ""
    if lines and re.match(r"\s*RAISONNEMENT\s*:", lines[0], re.IGNORECASE):
        reasoning = lines[0].split(":", 1)[1].strip()
        lines = lines[1:]
    if any(ln.strip() == "---" for ln in lines):  # coupe au 1er séparateur
        after, seen = [], False
        for ln in lines:
            if not seen and ln.strip() == "---":
                seen = True
                continue
            if seen:
                after.append(ln)
        lines = after
    return reasoning, "\n".join(lines).strip()


def draft_email(kind: str, ctx: str, demande_id: str) -> dict:
    """Rédige le brouillon d'email (Haiku) pour la décision `kind`.

    Renvoie {to, subject, body, reasoning} — `reasoning` est une phrase courte exposant l'approche de
    rédaction de l'agent (chain of thought minimaliste affichée dans l'interface).
    """
    consigne = CONSIGNES.get(kind, CONSIGNES["accord"])
    system = ("Tu es l'assistant d'un conseiller crédit dans une banque française. "
              "Tu rédiges des emails clairs et professionnels (formule d'appel, corps, formule de "
              "politesse, signature « Le service crédit »), en TEXTE BRUT (aucun formatage markdown : "
              "pas d'astérisques, pas de #, pas de puces). "
              "Structure ta réponse EXACTEMENT ainsi : la première ligne commence par « RAISONNEMENT: » "
              "suivie d'une phrase courte (max 25 mots) décrivant ton approche de rédaction ; puis une "
              "ligne contenant uniquement « --- » ; puis le corps de l'email.")
    user = f"{consigne}\n\nContexte du dossier :\n{ctx}"
    client = anthropic.Anthropic()
    resp = client.messages.create(model=MODEL, max_tokens=900, system=system,
                                  messages=[{"role": "user", "content": user}])
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    reasoning, body = _parse_draft(raw)
    return {"to": recipient(kind), "subject": subject_for(kind, demande_id),
            "body": body, "reasoning": reasoning}


def _log(to: str, subject: str, body: str, sent: bool) -> None:
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tag = "SENT" if sent else "SIMULATED"
    with open(OUTBOX, "a", encoding="utf-8") as fh:
        fh.write(f"\n===== [{tag}] {stamp} =====\nTo: {to}\nFrom: {SENDER}\nSubject: {subject}\n\n{body}\n")


def send_email(to: str, subject: str, body: str) -> dict:
    """Envoie l'email via SMTP. Sans SMTP_APP_PASSWORD -> simulation (journalisé, non envoyé)."""
    pw = os.getenv("SMTP_APP_PASSWORD")
    if not pw:
        _log(to, subject, body, sent=False)
        return {"sent": False, "simulated": True, "to": to,
                "detail": "Simulation : aucun SMTP_APP_PASSWORD configuré, l'email n'a pas été envoyé "
                          "(mais il est journalisé dans data/outbox.log)."}
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, SENDER, to
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(SENDER, pw)
            s.sendmail(SENDER, [to], msg.as_string())
    except Exception as e:  # noqa: BLE001
        _log(to, subject, body, sent=False)
        return {"sent": False, "simulated": False, "to": to, "detail": f"Échec de l'envoi : {e}"}
    _log(to, subject, body, sent=True)
    return {"sent": True, "simulated": False, "to": to, "detail": "Email envoyé avec succès."}
