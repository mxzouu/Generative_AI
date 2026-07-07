"""Modèle ML léger et explicable de scoring de fraude.

LogisticRegression (class_weight='balanced') sur features standardisées : la
contribution d'une feature à une prédiction est exactement coefficient × valeur
standardisée (log-odds), donc `explain` renvoie les vrais facteurs de LA décision,
pas des importances globales. C'est le tool MCP `score_claim` qui l'expose à l'agent.

API :  train(df) · predict_proba(feat_row) · explain(feat_row) · score(feat_row)
       save(path) / FraudModel.load(path)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES, FEATURE_LABELS, engineer

RISK_BANDS = [(0.65, "high"), (0.35, "medium"), (0.0, "low")]


def risk_band(probability: float) -> str:
    for threshold, band in RISK_BANDS:
        if probability >= threshold:
            return band
    return "low"


class FraudModel:
    def __init__(self) -> None:
        self.pipeline: Pipeline | None = None
        self.metrics: dict = {}
        self.trained_at: str | None = None

    # ------------------------------------------------------------------ train
    def train(self, df: pd.DataFrame) -> dict:
        """Entraîne sur les lignes étiquetées de `df` (label ∈ {legit, fraud}); renvoie les métriques."""
        labeled = df[df["label"].isin(["legit", "fraud"])]
        if labeled["label"].nunique() < 2:
            raise ValueError("Il faut au moins un exemple de chaque classe (legit / fraud).")
        X = engineer(df).loc[labeled["claim_id"]].to_numpy()
        y = (labeled["label"] == "fraud").astype(int).to_numpy()

        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ])
        self.pipeline.fit(X, y)
        self.trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.metrics = {
            "n_train": int(len(y)),
            "n_fraud": int(y.sum()),
            "train_auc": round(float(roc_auc_score(y, self.pipeline.predict_proba(X)[:, 1])), 4),
        }
        return self.metrics

    # ---------------------------------------------------------------- scoring
    def _row(self, feat_row: pd.Series | pd.DataFrame) -> np.ndarray:
        if isinstance(feat_row, pd.DataFrame):
            feat_row = feat_row.iloc[0]
        return feat_row[FEATURES].to_numpy(dtype=float).reshape(1, -1)

    def predict_proba(self, feat_row: pd.Series | pd.DataFrame) -> float:
        """Probabilité de fraude d'un sinistre (sa ligne de features `engineer`)."""
        return float(self.pipeline.predict_proba(self._row(feat_row))[0, 1])

    def explain(self, feat_row: pd.Series | pd.DataFrame, top_n: int = 5) -> list[dict]:
        """Top facteurs de CETTE prédiction : contribution = coef × valeur standardisée (log-odds)."""
        x = self._row(feat_row)
        scaled = self.pipeline.named_steps["scaler"].transform(x)[0]
        coefs = self.pipeline.named_steps["clf"].coef_[0]
        contributions = coefs * scaled
        order = np.argsort(-np.abs(contributions))[:top_n]
        return [
            {
                "factor": FEATURE_LABELS[FEATURES[i]],
                "feature": FEATURES[i],
                "value": round(float(x[0, i]), 2),
                "contribution": round(float(contributions[i]), 3),
                "effect": "augmente le risque" if contributions[i] > 0 else "diminue le risque",
            }
            for i in order
        ]

    def score(self, feat_row: pd.Series | pd.DataFrame, top_n: int = 5) -> dict:
        """Le contrat du tool MCP score_claim : { probability, risk_band, top_factors }."""
        p = self.predict_proba(feat_row)
        return {
            "probability": round(p, 3),
            "risk_band": risk_band(p),
            "top_factors": self.explain(feat_row, top_n=top_n),
        }

    # ------------------------------------------------------------ persistence
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self.pipeline, "metrics": self.metrics,
                     "trained_at": self.trained_at, "features": FEATURES}, path)

    @classmethod
    def load(cls, path: str | Path) -> "FraudModel":
        blob = joblib.load(path)
        if blob.get("features") != FEATURES:
            raise ValueError("Le modèle persisté ne correspond pas aux features actuelles — ré-entraîner (ml/train.py).")
        model = cls()
        model.pipeline = blob["pipeline"]
        model.metrics = blob.get("metrics", {})
        model.trained_at = blob.get("trained_at")
        return model
