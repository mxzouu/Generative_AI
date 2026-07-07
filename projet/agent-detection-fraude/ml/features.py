"""Feature engineering pour le scoring de fraude.

Les features encodent les signaux du §7 du README (montant aberrant, sinistre juste
après souscription, identifiants partagés, incohérences de dates, montants ronds,
descriptions vagues, réclamations répétées). Elles se calculent sur le DataFrame
COMPLET — plusieurs features ont besoin du contexte dataset (norme de montant par
type, identifiants partagés entre assurés) — puis le modèle consomme la ligne du
sinistre visé. Train et serving passent par la même fonction `engineer`, donc pas
de dérive train/serve.
"""
from __future__ import annotations

import pandas as pd

FEATURES = [
    "amount",
    "amount_zscore_type",
    "days_policy_to_incident",
    "incident_before_coverage",
    "new_policy_claim",
    "report_delay_days",
    "incident_weekend",
    "round_amount",
    "desc_word_count",
    "n_prior_claims",
    "shared_iban",
    "shared_phone",
    "shared_address",
]

# Libellés lisibles renvoyés au conseiller dans top_factors.
FEATURE_LABELS = {
    "amount": "montant du sinistre",
    "amount_zscore_type": "écart du montant vs la norme de la catégorie",
    "days_policy_to_incident": "délai souscription → incident",
    "incident_before_coverage": "incident survenu AVANT le début de couverture",
    "new_policy_claim": "sinistre dans les 30 jours après la souscription",
    "report_delay_days": "délai incident → déclaration",
    "incident_weekend": "incident un week-end",
    "round_amount": "montant rond",
    "desc_word_count": "longueur de la description (courte = vague)",
    "n_prior_claims": "nombre de sinistres antérieurs de l'assuré",
    "shared_iban": "IBAN partagé avec d'autres sinistres d'assurés différents",
    "shared_phone": "téléphone partagé avec d'autres sinistres d'assurés différents",
    "shared_address": "adresse partagée avec d'autres sinistres d'assurés différents",
}


def _shared_count(d: pd.DataFrame, col: str) -> pd.Series:
    """Nb d'AUTRES sinistres portant le même identifiant mais un assuré différent (signal ring)."""
    total = d.groupby(col)[col].transform("size")
    same_customer = d.groupby([col, "customer_id"])[col].transform("size")
    return (total - same_customer).astype(int)


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame brut (colonnes du CSV) -> DataFrame de features, indexé par claim_id."""
    d = df.copy()
    for col in ("date", "incident_date", "policy_start"):
        d[col] = pd.to_datetime(d[col])

    out = pd.DataFrame(index=d["claim_id"])
    out["amount"] = d["amount"].to_numpy()

    stats = d.groupby("type")["amount"].agg(["mean", "std"])
    stats["std"] = stats["std"].fillna(1.0).clip(lower=1.0)
    mean = d["type"].map(stats["mean"]).to_numpy()
    std = d["type"].map(stats["std"]).to_numpy()
    out["amount_zscore_type"] = (d["amount"].to_numpy() - mean) / std

    days_cov = (d["incident_date"] - d["policy_start"]).dt.days
    out["days_policy_to_incident"] = days_cov.to_numpy()
    out["incident_before_coverage"] = (days_cov < 0).astype(int).to_numpy()
    out["new_policy_claim"] = days_cov.between(0, 30).astype(int).to_numpy()

    out["report_delay_days"] = (d["date"] - d["incident_date"]).dt.days.to_numpy()
    out["incident_weekend"] = (d["incident_date"].dt.dayofweek >= 5).astype(int).to_numpy()
    out["round_amount"] = (d["amount"] % 100 == 0).astype(int).to_numpy()
    out["desc_word_count"] = d["description"].fillna("").str.split().str.len().to_numpy()

    # Sinistres antérieurs du même assuré (ordre chronologique de déclaration).
    order = d.sort_values("date").groupby("customer_id").cumcount()
    out["n_prior_claims"] = order.reindex(d.index).to_numpy()

    for col in ("iban", "phone", "address"):
        out[f"shared_{col}"] = _shared_count(d, col).to_numpy()

    return out[FEATURES]
