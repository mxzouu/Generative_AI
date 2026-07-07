"""Entraîne le modèle de scoring sur data/claims.csv et le persiste dans models/.

Usage :  python ml/train.py     (après avoir généré data/claims.csv)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252 vs accents/flèches

from ml.features import FEATURE_LABELS, FEATURES  # noqa: E402
from ml.model import FraudModel  # noqa: E402

CLAIMS_CSV = PROJECT / "data" / "claims.csv"
MODEL_PATH = PROJECT / "models" / "fraud_model.joblib"


def main() -> None:
    df = pd.read_csv(CLAIMS_CSV, dtype={"label": "string"}).fillna({"label": ""})
    model = FraudModel()
    metrics = model.train(df)
    model.save(MODEL_PATH)

    print(f"OK -> {MODEL_PATH}")
    print(f"  metrics: {metrics}")
    coefs = model.pipeline.named_steps["clf"].coef_[0]
    print("  coefficients (poids global de chaque signal) :")
    for name, coef in sorted(zip(FEATURES, coefs), key=lambda t: -abs(t[1])):
        print(f"    {coef:+.3f}  {FEATURE_LABELS[name]}")


if __name__ == "__main__":
    main()
