"""Source unique de vérité des features de scoring crédit.

Le point critique du projet (cf. README §7.1) : le CSV d'entraînement et le vecteur de
features construit au serving pour un dossier réel DOIVENT être identiques. On garantit
ça en passant TOUJOURS par `compute_features(ctx)` — que ce soit à la génération du CSV
(scripts/generate_training_csv.py) ou au scoring d'un dossier de la pile (app/credit_server.py).

`ctx` = dictionnaire de valeurs brutes issues de la BDD (client + crédit/dossier + agrégats).
`compute_features(ctx)` -> dict des 11 features du modèle, dans l'ordre de FEATURES.
"""
from __future__ import annotations

# Ordre canonique des features (colonnes du CSV, entrée du modèle).
FEATURES = [
    "age",
    "revenu_mensuel_net",
    "anciennete_emploi_mois",
    "type_contrat_encoded",
    "montant_demande",
    "duree_mois",
    "taux_endettement",
    "nb_credits_en_cours",
    "nb_incidents_12_mois",
    "nb_jours_retard_max",
    "ratio_garantie_montant",
]
TARGET = "target"  # 0 = bon payeur, 1 = défaut

# Libellés lisibles (pour l'explication SHAP côté explain_score).
FEATURE_LABELS = {
    "age": "Âge de l'emprunteur",
    "revenu_mensuel_net": "Revenu mensuel net",
    "anciennete_emploi_mois": "Ancienneté dans l'emploi",
    "type_contrat_encoded": "Type de contrat",
    "montant_demande": "Montant demandé",
    "duree_mois": "Durée du crédit",
    "taux_endettement": "Taux d'endettement",
    "nb_credits_en_cours": "Nombre de crédits en cours",
    "nb_incidents_12_mois": "Incidents de paiement (12 derniers mois)",
    "nb_jours_retard_max": "Retard de paiement maximum",
    "ratio_garantie_montant": "Garantie apportée (part du montant)",
}

# Encodage ordinal du contrat : plus la valeur est haute, plus le profil est précaire.
TYPE_CONTRAT_ENCODING = {
    "CDI": 0,
    "indépendant": 1,
    "CDD": 2,
    "sans emploi": 3,
}

# Barème de taux nominal annuel appliqué par type de crédit (utilisé pour estimer la
# mensualité d'un NOUVEAU dossier au serving). Cohérent avec grille_de_risque.pdf.
TAUX_PAR_TYPE = {
    "immo": 0.035,
    "auto": 0.045,
    "conso": 0.065,
    "renouvelable": 0.15,
}


def mensualite(montant: float, taux_annuel: float, duree_mois: int) -> float:
    """Mensualité d'un prêt amortissable (formule standard). Taux 0 -> linéaire."""
    duree_mois = max(int(duree_mois), 1)
    if taux_annuel <= 0:
        return round(montant / duree_mois, 2)
    t = taux_annuel / 12
    m = montant * t / (1 - (1 + t) ** (-duree_mois))
    return round(m, 2)


def compute_features(ctx: dict) -> dict:
    """Transforme un contexte brut en le vecteur de features du modèle.

    Clés attendues dans `ctx` :
      age, revenu_mensuel_net, anciennete_emploi_mois, type_contrat,
      montant_demande, duree_mois, mensualite_dossier,
      mensualites_autres_en_cours, nb_credits_en_cours,
      nb_incidents_12_mois, nb_jours_retard_max, valeur_garantie
    """
    revenu = max(float(ctx["revenu_mensuel_net"]), 1.0)
    charges = float(ctx["mensualite_dossier"]) + float(ctx.get("mensualites_autres_en_cours", 0.0))
    montant = max(float(ctx["montant_demande"]), 1.0)
    return {
        "age": int(ctx["age"]),
        "revenu_mensuel_net": round(revenu, 2),
        "anciennete_emploi_mois": int(ctx["anciennete_emploi_mois"]),
        "type_contrat_encoded": TYPE_CONTRAT_ENCODING.get(ctx["type_contrat"], 3),
        "montant_demande": round(montant, 2),
        "duree_mois": int(ctx["duree_mois"]),
        "taux_endettement": round(min(charges / revenu, 3.0), 4),
        "nb_credits_en_cours": int(ctx["nb_credits_en_cours"]),
        "nb_incidents_12_mois": int(ctx["nb_incidents_12_mois"]),
        "nb_jours_retard_max": int(ctx["nb_jours_retard_max"]),
        "ratio_garantie_montant": round(float(ctx.get("valeur_garantie", 0.0)) / montant, 4),
    }


def feature_vector(ctx: dict) -> list[float]:
    """Le vecteur ordonné selon FEATURES, prêt pour le modèle."""
    feats = compute_features(ctx)
    return [float(feats[name]) for name in FEATURES]
