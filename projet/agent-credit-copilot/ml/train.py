"""Entraîne le modèle de scoring sur le CSV et persiste models/credit_model.joblib.

Prérequis : scripts/generate_training_csv.py déjà exécuté.
Usage :  python ml/train.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
from ml.features import FEATURES, TARGET  # noqa: E402
from ml.model import CreditModel  # noqa: E402

CSV_PATH = PROJECT / "data" / "credit_scoring_dataset.csv"
MODEL_PATH = PROJECT / "models" / "credit_model.joblib"


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    X = df[FEATURES].to_numpy(dtype=float)
    y = df[TARGET].to_numpy(dtype=int)

    model = CreditModel()
    metrics = model.train(X, y)
    model.save(MODEL_PATH)

    print(f"[OK] Modele entraine : {MODEL_PATH}")
    print(f"   {metrics}")
    # importances globales (contrôle de bon sens : les bons drivers doivent ressortir)
    imp = sorted(zip(FEATURES, model.clf.feature_importances_), key=lambda t: -t[1])
    print("   Top features (importance globale) :")
    for name, val in imp[:6]:
        print(f"     {val:6.3f}  {name}")


if __name__ == "__main__":
    main()
