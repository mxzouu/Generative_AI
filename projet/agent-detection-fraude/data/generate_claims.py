"""Générateur de sinistres synthétiques (STUB — sera remplacé par un vrai dataset).

Produit data/claims.csv : ~45 sinistres historiques étiquetés (legit / fraud) sur
janv-juin 2026, + 18 sinistres « du jour » (2026-07-06, non étiquetés) dont 4 piégés
selon les signaux du §7 du README : montant aberrant/rond, sinistre juste après la
souscription, incident hors couverture, IBAN partagé entre assurés (ring), description
vague, week-end. Les fraudes historiques plantent les MÊMES signaux pour que le modèle
ML les apprenne. Déterministe (seed fixe) : régénérable à l'identique.

Usage :  python data/generate_claims.py
"""
from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252 vs accents
random.seed(42)

HERE = Path(__file__).resolve().parent
OUT = HERE / "claims.csv"

TODAY = date(2026, 7, 6)  # la « journée à analyser » de la démo

COLUMNS = [
    "claim_id", "date", "customer_id", "policy_id", "type", "amount",
    "incident_date", "policy_start", "iban", "phone", "address", "description", "label",
]

# Normes de montant par type de sinistre (moyenne, écart-type) — les fraudes s'en écartent.
AMOUNT_NORMS = {"auto": (2200, 600), "habitation": (3600, 1000)}

LEGIT_DESCS = {
    "auto": [
        "Collision à faible vitesse sur un parking, pare-chocs arrière et feu gauche endommagés. Constat amiable signé, photos jointes.",
        "Bris de glace sur le pare-brise suite à une projection de gravillons sur l'autoroute. Devis du réparateur agréé joint.",
        "Accrochage en sortie de rond-point, aile avant droite enfoncée. Constat contradictoire avec le tiers, rapport de police joint.",
        "Rétroviseur et portière rayés par un véhicule en stationnement, tiers identifié. Photos et témoignage du gardien joints.",
        "Grêle sur le capot et le toit pendant l'orage du week-end, plusieurs impacts constatés. Expertise demandée, photos jointes.",
    ],
    "habitation": [
        "Dégât des eaux dans la cuisine suite à une fuite du lave-vaisselle, parquet et plinthes touchés. Facture du plombier jointe.",
        "Infiltration par la toiture après la tempête, plafond de la chambre taché. Rapport du couvreur et photos joints.",
        "Cambriolage par effraction de la porte-fenêtre : télévision et ordinateur portable dérobés. Dépôt de plainte joint.",
        "Rupture du ballon d'eau chaude, salle de bain et couloir inondés. Intervention d'urgence facturée, photos jointes.",
        "Vitre du salon brisée par un ballon, remplacement par un vitrier. Facture et attestation du voisin jointes.",
    ],
}

VAGUE_DESCS = [
    "Dégâts importants sur le véhicule.",
    "Sinistre important, facture à venir.",
    "Vol de matériel au domicile.",
    "Gros dégâts suite à un incident.",
    "Véhicule endommagé, réparations nécessaires.",
]

FIRST_STREETS = [
    "12 rue des Lilas", "3 avenue Jean Jaurès", "45 boulevard Voltaire", "8 impasse des Peupliers",
    "27 rue de la République", "5 allée des Tilleuls", "19 rue Pasteur", "33 avenue de la Gare",
    "7 rue des Acacias", "14 place du Marché", "22 rue Victor Hugo", "9 chemin des Vignes",
    "31 rue des Écoles", "6 avenue Foch", "18 rue du Moulin", "25 rue Gambetta",
]
CITIES = ["Lyon", "Nantes", "Lille", "Toulouse", "Rennes", "Dijon", "Angers", "Metz"]

# Identifiants « plantés » pour le ring : même IBAN chez des assurés différents.
RING_IBAN = "FR7630001007941234567890185"
SHARED_PHONE = "0699887766"


def _iban() -> str:
    return "FR76" + "".join(str(random.randint(0, 9)) for _ in range(23))


def _phone() -> str:
    return "06" + "".join(str(random.randint(0, 9)) for _ in range(8))


def _address() -> str:
    return f"{random.choice(FIRST_STREETS)}, {random.choice(CITIES)}"


def _weekday(d: date) -> date:
    """Décale au vendredi précédent si d tombe un week-end (les legit évitent le week-end)."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def make_customers(n: int) -> list[dict]:
    customers = []
    for i in range(1, n + 1):
        customers.append({
            "customer_id": f"CUS-{i:03d}",
            "policy_id": f"POL-{i:03d}",
            "iban": _iban(),
            "phone": _phone(),
            "address": _address(),
            # Polices anciennes pour la plupart (souscrites en 2024-2025)
            "policy_start": date(2024, 1, 1) + timedelta(days=random.randint(0, 600)),
        })
    return customers


def legit_claim(cid: int, cust: dict, day: date) -> dict:
    ctype = random.choice(list(AMOUNT_NORMS))
    mean, std = AMOUNT_NORMS[ctype]
    amount = round(max(300, random.gauss(mean, std)), 2)
    incident = _weekday(day - timedelta(days=random.randint(1, 5)))
    return {
        "claim_id": f"CLM-{cid:04d}",
        "date": day.isoformat(),
        "customer_id": cust["customer_id"],
        "policy_id": cust["policy_id"],
        "type": ctype,
        "amount": amount,
        "incident_date": incident.isoformat(),
        "policy_start": cust["policy_start"].isoformat(),
        "iban": cust["iban"],
        "phone": cust["phone"],
        "address": cust["address"],
        "description": random.choice(LEGIT_DESCS[ctype]),
        "label": "legit",
    }


def fraud_claim(cid: int, cust: dict, day: date, *, ctype: str, amount: float,
                incident: date, policy_start: date | None = None,
                iban: str | None = None, phone: str | None = None,
                desc: str | None = None) -> dict:
    return {
        "claim_id": f"CLM-{cid:04d}",
        "date": day.isoformat(),
        "customer_id": cust["customer_id"],
        "policy_id": cust["policy_id"],
        "type": ctype,
        "amount": amount,
        "incident_date": incident.isoformat(),
        "policy_start": (policy_start or cust["policy_start"]).isoformat(),
        "iban": iban or cust["iban"],
        "phone": phone or cust["phone"],
        "address": cust["address"],
        "description": desc or random.choice(VAGUE_DESCS),
        "label": "fraud",
    }


def main() -> None:
    customers = make_customers(30)
    rows: list[dict] = []
    cid = 0

    # ---- 37 sinistres historiques légitimes (janv -> juin 2026) -------------
    hist_days = sorted(date(2026, 1, 5) + timedelta(days=random.randint(0, 170)) for _ in range(37))
    for day in hist_days:
        cid += 1
        rows.append(legit_claim(cid, random.choice(customers), _weekday(day)))

    # ---- 8 fraudes historiques CONFIRMÉES (signaux plantés, cf. §7) ---------
    # F1 : montant aberrant + rond + description vague (auto)
    cid += 1
    rows.append(fraud_claim(cid, customers[0], date(2026, 2, 13), ctype="auto",
                            amount=9500.0, incident=date(2026, 2, 8),
                            desc="Véhicule fortement endommagé, montant selon devis."))
    # F2 : sinistre 9 jours après la souscription
    cid += 1
    rows.append(fraud_claim(cid, customers[1], date(2026, 3, 6), ctype="habitation",
                            amount=7000.0, incident=date(2026, 3, 4),
                            policy_start=date(2026, 2, 23)))
    # F3 : incident AVANT le début de couverture
    cid += 1
    rows.append(fraud_claim(cid, customers[2], date(2026, 3, 20), ctype="auto",
                            amount=4800.0, incident=date(2026, 3, 1),
                            policy_start=date(2026, 3, 10)))
    # F4 : membre du ring (IBAN partagé) — la référence historique
    cid += 1
    rows.append(fraud_claim(cid, customers[3], date(2026, 4, 10), ctype="auto",
                            amount=5200.0, incident=date(2026, 4, 5), iban=RING_IBAN,
                            desc="Collision avec un tiers, véhicule hors d'usage."))
    # F5 : assuré multi-réclamant (customers[4] a déjà des sinistres plus haut)
    cid += 1
    rows.append(fraud_claim(cid, customers[4], date(2026, 4, 24), ctype="habitation",
                            amount=6000.0, incident=date(2026, 4, 19)))
    # F6 : incident un week-end + montant rond + vague
    cid += 1
    rows.append(fraud_claim(cid, customers[5], date(2026, 5, 12), ctype="auto",
                            amount=8000.0, incident=date(2026, 5, 10)))  # un dimanche
    # F7 : montant aberrant habitation
    cid += 1
    rows.append(fraud_claim(cid, customers[6], date(2026, 5, 29), ctype="habitation",
                            amount=15000.0, incident=date(2026, 5, 24),
                            desc="Cambriolage, liste des biens à venir."))
    # F8 : téléphone partagé entre deux assurés différents (doublon organisé)
    cid += 1
    rows.append(fraud_claim(cid, customers[7], date(2026, 6, 12), ctype="habitation",
                            amount=5500.0, incident=date(2026, 6, 7), phone=SHARED_PHONE))
    cid += 1
    rows.append(fraud_claim(cid, customers[8], date(2026, 6, 15), ctype="habitation",
                            amount=5500.0, incident=date(2026, 6, 7), phone=SHARED_PHONE,
                            desc="Vol de matériel au domicile, mêmes biens déclarés."))

    # Quelques sinistres supplémentaires pour customers[4] (profil multi-réclamant)
    for day in (date(2026, 2, 3), date(2026, 3, 17)):
        cid += 1
        rows.append(legit_claim(cid, customers[4], _weekday(day)))

    # ---- 18 sinistres « du jour » (2026-07-06), non étiquetés ---------------
    # 14 d'apparence normale
    for _ in range(14):
        cid += 1
        c = legit_claim(cid, random.choice(customers), TODAY)
        c["label"] = ""
        rows.append(c)

    # T1 : montant aberrant + rond + vague + incident le week-end (4-5 juillet)
    cid += 1
    t1 = fraud_claim(cid, customers[10], TODAY, ctype="auto", amount=9800.0,
                     incident=date(2026, 7, 5), desc="Dégâts importants sur le véhicule.")
    t1["label"] = ""
    rows.append(t1)
    # T2 : souscription le 28 juin, sinistre le 4 juillet
    cid += 1
    t2 = fraud_claim(cid, customers[11], TODAY, ctype="habitation", amount=6500.0,
                     incident=date(2026, 7, 4), policy_start=date(2026, 6, 28),
                     desc="Sinistre important, facture à venir.")
    t2["label"] = ""
    rows.append(t2)
    # T3 + T4 : le ring refait surface — deux assurés différents, même IBAN que F4
    for cust in (customers[12], customers[13]):
        cid += 1
        t = fraud_claim(cid, cust, TODAY, ctype="auto", amount=5000.0,
                        incident=date(2026, 7, 3), iban=RING_IBAN,
                        desc="Collision avec un tiers, véhicule hors d'usage.")
        t["label"] = ""
        rows.append(t)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    n_fraud = sum(1 for r in rows if r["label"] == "fraud")
    n_new = sum(1 for r in rows if r["label"] == "")
    trapped = [r["claim_id"] for r in rows if r["label"] == "" and r["claim_id"] in
               {t1["claim_id"], t2["claim_id"]} | {rows[-1]["claim_id"], rows[-2]["claim_id"]}]
    print(f"OK -> {OUT}")
    print(f"  {len(rows)} sinistres : {n_fraud} fraudes historiques confirmées, {n_new} du {TODAY} (non étiquetés)")
    print(f"  Cas piégés du jour : {trapped}")


if __name__ == "__main__":
    main()
