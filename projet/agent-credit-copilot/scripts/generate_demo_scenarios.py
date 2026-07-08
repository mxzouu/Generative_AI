"""Score toute la pile de demandes et sélectionne 4 dossiers de démo représentatifs.

Un dossier par cas : accord (risque faible), analyse manuelle (modéré), refus (élevé),
escalade (critique, no_auto_processing). Écrit data/demo_scenarios.json avec, pour chaque
cas, le demande_id, le client, le score et une question réglementaire suggérée au chatbot.
Sert aussi de test de bout en bout du chemin de scoring (ctx_from_demande -> modèle).

Prérequis : DB + modèle entraînés.
Usage :  python scripts/generate_demo_scenarios.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
from ml.context import ctx_from_demande  # noqa: E402
from ml.features import feature_vector  # noqa: E402
from ml.model import CreditModel  # noqa: E402

DB_PATH = PROJECT / "data" / "credit_copilot.db"
MODEL_PATH = PROJECT / "models" / "credit_model.joblib"
OUT_PATH = PROJECT / "data" / "demo_scenarios.json"

QUESTIONS = {
    "accord": "Quel est le taux d'endettement maximal autorisé pour accorder un crédit ?",
    "analyse manuelle": "Dans quels cas un dossier doit-il passer en analyse manuelle ?",
    "refus": "Que dit la grille de scoring pour une probabilité de défaut supérieure à 60 % ?",
    "escalade": "Quelle est la procédure quand le score est en risque critique ?",
}


def pick(scored: list[dict]) -> dict:
    """Choisit un dossier par cas de démo à partir des dossiers scorés."""
    by_p = sorted(scored, key=lambda s: s["probability_default"])
    chosen = {}
    escalade = [s for s in by_p if s["no_auto_processing"]]
    refus = [s for s in by_p if s["recommandation"] == "refus" and not s["no_auto_processing"]]
    analyse = [s for s in by_p if s["recommandation"] == "analyse manuelle"]
    accord = [s for s in by_p if s["recommandation"] == "accord"]
    if accord:
        chosen["accord"] = accord[0]
    if analyse:
        chosen["analyse manuelle"] = analyse[len(analyse) // 2]
    if refus:
        chosen["refus"] = refus[-1]
    if escalade:
        chosen["escalade"] = escalade[-1]
    return chosen


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    model = CreditModel.load(MODEL_PATH)

    scored = []
    for d in conn.execute("SELECT demande_id, client_id, type_credit, montant_demande FROM demandes"):
        res = model.score(feature_vector(ctx_from_demande(conn, d["demande_id"])))
        scored.append({"demande_id": d["demande_id"], "client_id": d["client_id"],
                       "type_credit": d["type_credit"], "montant_demande": d["montant_demande"],
                       **{k: res[k] for k in ("probability_default", "decision_band",
                                              "recommandation", "no_auto_processing")}})

    chosen = pick(scored)
    scenarios = []
    for cas, s in chosen.items():
        scenarios.append({"cas": cas, "question_chatbot": QUESTIONS[cas], **s})

    OUT_PATH.write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")

    dist = {}
    for s in scored:
        dist[s["recommandation"]] = dist.get(s["recommandation"], 0) + 1
    print(f"[OK] Scenarios ecrits : {OUT_PATH}")
    print(f"   Pile de {len(scored)} dossiers scores. Repartition : {dist}")
    for sc in scenarios:
        print(f"   [{sc['cas']:>16}] {sc['demande_id']} {sc['client_id']} "
              f"p_defaut={sc['probability_default']:.2f} -> {sc['recommandation']}")
    conn.close()


if __name__ == "__main__":
    main()
