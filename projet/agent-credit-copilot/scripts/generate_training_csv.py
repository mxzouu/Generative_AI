"""Dérive le CSV d'entraînement du modèle de scoring DEPUIS la base SQLite.

Une ligne = un crédit historique. Les features sont construites par le MÊME chemin que
le serving (ml.context.ctx_from_credit -> ml.features.compute_features) : c'est la garantie
de cohérence CSV <-> BDD (README §7.1). target = 1 si le crédit est en défaut, 0 sinon.

Prérequis : scripts/generate_sqlite_db.py déjà exécuté.
Usage :  python scripts/generate_training_csv.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
from ml.context import ctx_from_credit  # noqa: E402
from ml.features import FEATURES, TARGET, compute_features  # noqa: E402

DB_PATH = PROJECT / "data" / "credit_copilot.db"
CSV_PATH = PROJECT / "data" / "credit_scoring_dataset.csv"


def build() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    credits = conn.execute("SELECT * FROM credits_historiques").fetchall()

    rows, n_pos = [], 0
    for cr in credits:
        feats = compute_features(ctx_from_credit(conn, cr))
        target = 1 if cr["statut"] == "défaut" else 0
        n_pos += target
        rows.append([feats[f] for f in FEATURES] + [target])

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FEATURES + [TARGET])
        w.writerows(rows)

    print(f"[OK] CSV genere : {CSV_PATH}")
    print(f"   {len(rows)} lignes · {len(FEATURES)} features · taux de défaut = "
          f"{100*n_pos/max(len(rows),1):.1f}%")
    conn.close()


if __name__ == "__main__":
    build()
