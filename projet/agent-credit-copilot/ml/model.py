"""Modèle de scoring crédit : XGBoost + explication SHAP par prédiction.

Contrat exposé à l'agent (tools run_credit_score / explain_score) :
  score(feat) -> { probability_default, decision_band, recommandation,
                   no_auto_processing, top_factors }

`probability_default` ∈ [0,1] : proba que le dossier finisse en défaut (1 = risqué).
`top_factors` = contributions SHAP de CETTE prédiction (pas des importances globales).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import shap
from xgboost import XGBClassifier

from .features import FEATURE_LABELS, FEATURES

# Bandes de décision (seuils sur la proba de défaut, configurables).
SEUIL_FAIBLE = 0.30      # < : faible risque -> recommandation d'accord
SEUIL_ELEVE = 0.60       # >= : risque élevé -> recommandation de refus
SEUIL_CRITIQUE = 0.75    # >= : flag "pas de traitement auto" (escalade obligatoire)


def decision_band(p: float) -> str:
    if p >= SEUIL_ELEVE:
        return "risque élevé"
    if p >= SEUIL_FAIBLE:
        return "risque modéré"
    return "risque faible"


def recommandation(p: float) -> str:
    if p >= SEUIL_ELEVE:
        return "refus"
    if p >= SEUIL_FAIBLE:
        return "analyse manuelle"
    return "accord"


class CreditModel:
    def __init__(self) -> None:
        self.clf: XGBClassifier | None = None
        self.explainer: shap.TreeExplainer | None = None
        self.metrics: dict = {}
        self.trained_at: str | None = None

    # --------------------------------------------------------------- training
    def train(self, X: np.ndarray, y: np.ndarray) -> dict:
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import train_test_split

        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
        pos = max(int(ytr.sum()), 1)
        self.clf = XGBClassifier(
            n_estimators=250, max_depth=4, learning_rate=0.08,
            subsample=0.9, colsample_bytree=0.9,
            scale_pos_weight=(len(ytr) - pos) / pos,  # équilibre les classes
            eval_metric="auc", random_state=42,
        )
        self.clf.fit(Xtr, ytr)
        self.explainer = shap.TreeExplainer(self.clf)
        self.trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.metrics = {
            "n_train": int(len(ytr)), "n_test": int(len(yte)),
            "test_auc": round(float(roc_auc_score(yte, self.clf.predict_proba(Xte)[:, 1])), 4),
            "base_rate": round(float(y.mean()), 4),
        }
        return self.metrics

    # ---------------------------------------------------------------- scoring
    def predict_proba(self, feat_row: list[float]) -> float:
        x = np.asarray(feat_row, dtype=float).reshape(1, -1)
        return float(self.clf.predict_proba(x)[0, 1])

    def explain(self, feat_row: list[float], top_n: int = 5) -> list[dict]:
        x = np.asarray(feat_row, dtype=float).reshape(1, -1)
        vals = np.asarray(self.explainer.shap_values(x)).reshape(-1)
        order = np.argsort(-np.abs(vals))[:top_n]
        return [
            {
                "facteur": FEATURE_LABELS[FEATURES[i]],
                "feature": FEATURES[i],
                "valeur": round(float(x[0, i]), 2),
                "contribution": round(float(vals[i]), 3),
                "effet": "augmente le risque" if vals[i] > 0 else "diminue le risque",
            }
            for i in order
        ]

    def score(self, feat_row: list[float], top_n: int = 5) -> dict:
        p = self.predict_proba(feat_row)
        return {
            "probability_default": round(p, 3),
            "decision_band": decision_band(p),
            "recommandation": recommandation(p),
            "no_auto_processing": bool(p >= SEUIL_CRITIQUE),
            "top_factors": self.explain(feat_row, top_n=top_n),
        }

    # ------------------------------------------------------------ persistence
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"clf": self.clf, "metrics": self.metrics,
                     "trained_at": self.trained_at, "features": FEATURES}, path)

    @classmethod
    def load(cls, path: str | Path) -> "CreditModel":
        blob = joblib.load(path)
        if blob.get("features") != FEATURES:
            raise ValueError("Modèle persisté incompatible avec FEATURES actuelles — ré-entraîner (ml/train.py).")
        m = cls()
        m.clf = blob["clf"]
        m.explainer = shap.TreeExplainer(m.clf)
        m.metrics = blob.get("metrics", {})
        m.trained_at = blob.get("trained_at")
        return m
