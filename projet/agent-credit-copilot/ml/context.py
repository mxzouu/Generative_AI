"""Construction du `ctx` (contexte brut) depuis la BDD SQLite.

Un seul endroit sait interroger la base pour rassembler les valeurs brutes d'un dossier ;
`ml.features.compute_features` sait les transformer en features. Cette séparation garantit
que l'entraînement (ctx_from_credit) et le serving (ctx_from_demande) parlent le même langage.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

from .features import TAUX_PAR_TYPE, mensualite

REFERENCE_DATE = date(2026, 7, 1)


def _client(conn: sqlite3.Connection, client_id: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()


def _autres_mensualites_en_cours(conn, client_id: str, exclude_credit_id: str | None) -> tuple[float, int]:
    rows = conn.execute(
        "SELECT credit_id, mensualite FROM credits_historiques "
        "WHERE client_id = ? AND statut = 'en cours'", (client_id,)
    ).fetchall()
    total, n = 0.0, 0
    for r in rows:
        if exclude_credit_id and r["credit_id"] == exclude_credit_id:
            continue
        total += float(r["mensualite"])
        n += 1
    return total, n


def _incidents_window(conn, client_id: str, ref_iso: str, months: int = 12) -> tuple[int, int]:
    """(nb incidents dans la fenêtre de `months` avant ref, retard max jours) pour le client."""
    ref = datetime.fromisoformat(ref_iso).date()
    rows = conn.execute(
        "SELECT date_incident, nb_jours_retard FROM incidents WHERE client_id = ?", (client_id,)
    ).fetchall()
    nb, retard_max = 0, 0
    for r in rows:
        d = datetime.fromisoformat(r["date_incident"]).date()
        if 0 <= (ref - d).days <= months * 31:
            nb += 1
        retard_max = max(retard_max, int(r["nb_jours_retard"]))
    return nb, retard_max


def ctx_from_credit(conn: sqlite3.Connection, credit: sqlite3.Row) -> dict:
    """ctx d'un crédit HISTORIQUE (pour construire une ligne d'entraînement)."""
    cl = _client(conn, credit["client_id"])
    autres_mens, n_autres = _autres_mensualites_en_cours(conn, cl["client_id"], credit["credit_id"])
    nb_inc, retard_max = _incidents_window(conn, cl["client_id"], credit["date_debut"])
    val_gar = conn.execute(
        "SELECT COALESCE(SUM(valeur_estimee),0) v FROM garanties WHERE credit_id = ?",
        (credit["credit_id"],)
    ).fetchone()["v"]
    return {
        "age": cl["age"], "revenu_mensuel_net": cl["revenu_mensuel_net"],
        "anciennete_emploi_mois": cl["anciennete_emploi_mois"], "type_contrat": cl["type_contrat"],
        "montant_demande": credit["montant"], "duree_mois": credit["duree_mois"],
        "mensualite_dossier": credit["mensualite"], "mensualites_autres_en_cours": autres_mens,
        "nb_credits_en_cours": n_autres, "nb_incidents_12_mois": nb_inc,
        "nb_jours_retard_max": retard_max, "valeur_garantie": val_gar,
    }


def ctx_from_demande(conn: sqlite3.Connection, demande_id: str) -> dict:
    """ctx d'un dossier de la PILE (nouvelle demande) — utilisé au serving par run_credit_score."""
    conn.row_factory = sqlite3.Row
    d = conn.execute("SELECT * FROM demandes WHERE demande_id = ?", (demande_id,)).fetchone()
    if d is None:
        raise ValueError(f"demande {demande_id} introuvable")
    cl = _client(conn, d["client_id"])
    autres_mens, n_cours = _autres_mensualites_en_cours(conn, cl["client_id"], None)
    mens = d["mensualite_estimee"] or mensualite(
        d["montant_demande"], TAUX_PAR_TYPE.get(d["type_credit"], 0.06), d["duree_mois"])
    nb_inc, retard_max = _incidents_window(conn, cl["client_id"], d["date_demande"])
    return {
        "age": cl["age"], "revenu_mensuel_net": cl["revenu_mensuel_net"],
        "anciennete_emploi_mois": cl["anciennete_emploi_mois"], "type_contrat": cl["type_contrat"],
        "montant_demande": d["montant_demande"], "duree_mois": d["duree_mois"],
        "mensualite_dossier": mens, "mensualites_autres_en_cours": autres_mens,
        "nb_credits_en_cours": n_cours, "nb_incidents_12_mois": nb_inc,
        "nb_jours_retard_max": retard_max, "valeur_garantie": d["valeur_garantie_proposee"],
    }
