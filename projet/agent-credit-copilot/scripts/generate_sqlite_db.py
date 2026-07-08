"""Génère la base SQLite synthétique du Credit Copilot (données 100% mockées).

Un seul passage génératif cohérent :
  clients -> credits_historiques -> garanties -> incidents -> demandes (la pile à traiter)
  + table decisions (vide, alimentée ensuite par le tool record_decision).

Cohérence : le risque de défaut d'un crédit est tiré d'un modèle latent (contrat précaire,
faible ancienneté, endettement élevé, absence de garantie -> plus de défauts), et les incidents
sont générés corrélés au défaut. Le CSV d'entraînement (generate_training_csv.py) redérive
ensuite ses features de cette même base -> features cohérentes entre train et serving.

Tout est seedé (SEED) -> reproductible entre binômes.
Usage :  python scripts/generate_sqlite_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from faker import Faker

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
from ml.features import TAUX_PAR_TYPE, mensualite  # noqa: E402

SEED = 42
DB_PATH = PROJECT / "data" / "credit_copilot.db"
REFERENCE_DATE = date(2026, 7, 1)  # "aujourd'hui" figé pour la reproductibilité

N_CLIENTS = 500
N_DEMANDES = 50  # taille de la pile de dossiers à traiter

rng = np.random.default_rng(SEED)
fake = Faker("fr_FR")
Faker.seed(SEED)

# --- barèmes métier -----------------------------------------------------------
CSP = ["cadre", "profession intermédiaire", "employé", "ouvrier", "artisan", "sans emploi"]
CSP_W = [0.18, 0.20, 0.30, 0.18, 0.09, 0.05]
REVENU_RANGE = {  # (min, max) revenu mensuel net € par CSP
    "cadre": (3000, 8000), "profession intermédiaire": (2200, 4000),
    "employé": (1500, 2800), "ouvrier": (1400, 2500),
    "artisan": (1500, 6000), "sans emploi": (600, 1200),
}
CONTRAT_PAR_CSP = {  # (labels, poids)
    "cadre": (["CDI", "CDD", "indépendant"], [0.85, 0.08, 0.07]),
    "profession intermédiaire": (["CDI", "CDD", "indépendant"], [0.80, 0.15, 0.05]),
    "employé": (["CDI", "CDD"], [0.72, 0.28]),
    "ouvrier": (["CDI", "CDD"], [0.65, 0.35]),
    "artisan": (["indépendant", "CDI"], [0.85, 0.15]),
    "sans emploi": (["sans emploi"], [1.0]),
}
TYPES_CREDIT = ["conso", "auto", "immo", "renouvelable"]
TYPE_W = [0.40, 0.25, 0.20, 0.15]
MONTANT_RANGE = {"immo": (50_000, 400_000), "auto": (5_000, 40_000),
                 "conso": (1_000, 40_000), "renouvelable": (500, 6_000)}
DUREE_RANGE = {"immo": (120, 300), "auto": (12, 84), "conso": (6, 84), "renouvelable": (12, 60)}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def _rand_date(start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=int(rng.integers(0, max(span, 1))))


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS clients;
        DROP TABLE IF EXISTS credits_historiques;
        DROP TABLE IF EXISTS incidents;
        DROP TABLE IF EXISTS garanties;
        DROP TABLE IF EXISTS demandes;
        DROP TABLE IF EXISTS decisions;

        CREATE TABLE clients (
            client_id TEXT PRIMARY KEY,
            nom TEXT, prenom TEXT, date_naissance TEXT, age INTEGER,
            situation_familiale TEXT, profession TEXT, categorie_socio_pro TEXT,
            revenu_mensuel_net REAL, anciennete_emploi_mois INTEGER,
            type_contrat TEXT, adresse TEXT, code_postal TEXT, date_creation_compte TEXT
        );
        CREATE TABLE credits_historiques (
            credit_id TEXT PRIMARY KEY, client_id TEXT,
            type_credit TEXT, montant REAL, duree_mois INTEGER, taux REAL,
            date_debut TEXT, date_fin_prevue TEXT, statut TEXT, mensualite REAL,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY, client_id TEXT, credit_id TEXT,
            date_incident TEXT, type TEXT, montant_impaye REAL,
            nb_jours_retard INTEGER, regularise INTEGER,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );
        CREATE TABLE garanties (
            garantie_id TEXT PRIMARY KEY, client_id TEXT, credit_id TEXT,
            type TEXT, valeur_estimee REAL, statut TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );
        CREATE TABLE demandes (
            demande_id TEXT PRIMARY KEY, client_id TEXT,
            type_credit TEXT, montant_demande REAL, duree_mois INTEGER, taux REAL,
            mensualite_estimee REAL, valeur_garantie_proposee REAL,
            date_demande TEXT, statut TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );
        CREATE TABLE decisions (
            decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT, demande_id TEXT, date_decision TEXT, conseiller_id TEXT,
            decision TEXT, score_ml REAL, commentaire TEXT, tools_utilises TEXT
        );
        """
    )


def generate() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)

    clients, credits, incidents, garanties, demandes = [], [], [], [], []
    cred_seq = inc_seq = gar_seq = 0

    for i in range(1, N_CLIENTS + 1):
        cid = f"CLI{i:05d}"
        csp = rng.choice(CSP, p=CSP_W)
        labels, w = CONTRAT_PAR_CSP[csp]
        contrat = rng.choice(labels, p=w)
        rmin, rmax = REVENU_RANGE[csp]
        revenu = round(float(rng.uniform(rmin, rmax)), 2)
        age = int(rng.integers(21, 76))
        max_anc = max((age - 20) * 12, 0)
        anciennete = 0 if contrat == "sans emploi" else int(rng.integers(0, max_anc + 1))
        naissance = REFERENCE_DATE - timedelta(days=age * 365 + int(rng.integers(0, 365)))

        # precarité latente du client (pilote le taux de défaut de ses crédits)
        base_risk = (
            {"CDI": -0.3, "indépendant": 0.2, "CDD": 0.6, "sans emploi": 1.2}[contrat]
            - anciennete / 240.0
            - revenu / 5000.0
        )
        clients.append((
            cid, fake.last_name(), fake.first_name(), naissance.isoformat(), age,
            rng.choice(["célibataire", "marié(e)", "divorcé(e)", "pacsé(e)", "veuf(ve)"],
                       p=[0.34, 0.40, 0.12, 0.10, 0.04]),
            fake.job(), csp, revenu, anciennete, contrat,
            fake.street_address(), fake.postcode(),
            _rand_date(date(2005, 1, 1), date(2023, 1, 1)).isoformat(),
        ))

        n_credits = int(np.clip(rng.poisson(5), 0, 10))
        for _ in range(n_credits):
            cred_seq += 1
            tc = rng.choice(TYPES_CREDIT, p=TYPE_W)
            mmin, mmax = MONTANT_RANGE[tc]
            montant = round(float(rng.uniform(mmin, mmax)), 2)
            dmin, dmax = DUREE_RANGE[tc]
            duree = int(rng.integers(dmin, dmax + 1))
            taux = round(TAUX_PAR_TYPE[tc] + float(rng.uniform(-0.01, 0.02)), 4)
            debut = _rand_date(date(2016, 1, 1), REFERENCE_DATE - timedelta(days=90))
            fin = debut + timedelta(days=int(duree * 30.4))
            mens = mensualite(montant, taux, duree)
            crid = f"CR{cred_seq:06d}"

            # garantie (immo -> hypothèque quasi systématique ; auto -> nantissement fréquent)
            val_gar = 0.0
            if tc == "immo" or (tc == "auto" and rng.random() < 0.6) or (tc == "conso" and rng.random() < 0.15):
                gar_seq += 1
                gtype = {"immo": "hypotheque", "auto": "nantissement", "conso": "caution"}[tc]
                val_gar = round(montant * float(rng.uniform(0.6, 1.3)), 2)
                garanties.append((f"GAR{gar_seq:05d}", cid, crid, gtype, val_gar, "active"))

            charge_ratio = mens / revenu
            logit = (-1.7 + 2.6 * charge_ratio + 1.3 * base_risk
                     + (0.25 if duree > 72 else 0.0) - (0.9 if val_gar > 0 else 0.0))
            defaut = rng.random() < _sigmoid(logit)
            if defaut:
                statut = "défaut"
            else:
                statut = "soldé" if fin < REFERENCE_DATE else "en cours"
            credits.append((crid, cid, tc, montant, duree, taux, debut.isoformat(),
                            fin.isoformat(), statut, mens))

            # incidents corrélés au défaut
            n_inc = int(rng.integers(1, 5)) if defaut else (1 if rng.random() < 0.06 else 0)
            for _ in range(n_inc):
                inc_seq += 1
                incidents.append((
                    f"INC{inc_seq:05d}", cid, crid,
                    _rand_date(debut, min(fin, REFERENCE_DATE)).isoformat(),
                    rng.choice(["retard", "impaye", "rejet_prelevement"], p=[0.5, 0.35, 0.15]),
                    round(float(mens * rng.uniform(0.5, 2.0)), 2),
                    int(rng.integers(5, 120)),
                    int(0 if defaut else 1),
                ))

    # --- la pile de dossiers à traiter (nouvelles demandes) -------------------
    chosen = rng.choice([c[0] for c in clients], size=N_DEMANDES, replace=False)
    for j, cid in enumerate(chosen, start=1):
        tc = rng.choice(TYPES_CREDIT, p=TYPE_W)
        mmin, mmax = MONTANT_RANGE[tc]
        montant = round(float(rng.uniform(mmin, mmax)), 2)
        dmin, dmax = DUREE_RANGE[tc]
        duree = int(rng.integers(dmin, dmax + 1))
        taux = round(TAUX_PAR_TYPE[tc], 4)
        mens = mensualite(montant, taux, duree)
        val_gar = round(montant * float(rng.uniform(0.9, 1.2)), 2) if tc in ("immo", "auto") else 0.0
        demandes.append((f"DOS{j:04d}", cid, tc, montant, duree, taux, mens, val_gar,
                         _rand_date(REFERENCE_DATE - timedelta(days=20), REFERENCE_DATE).isoformat(),
                         "à traiter"))

    conn.executemany("INSERT INTO clients VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", clients)
    conn.executemany("INSERT INTO credits_historiques VALUES (?,?,?,?,?,?,?,?,?,?)", credits)
    conn.executemany("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?)", incidents)
    conn.executemany("INSERT INTO garanties VALUES (?,?,?,?,?,?)", garanties)
    conn.executemany("INSERT INTO demandes VALUES (?,?,?,?,?,?,?,?,?,?)", demandes)
    conn.commit()

    n_def = sum(1 for c in credits if c[8] == "défaut")
    print(f"[OK] Base generee : {DB_PATH}")
    print(f"   clients={len(clients)}  crédits={len(credits)} (défauts={n_def}, "
          f"{100*n_def/max(len(credits),1):.1f}%)  incidents={len(incidents)}  "
          f"garanties={len(garanties)}  demandes(pile)={len(demandes)}")
    conn.close()


if __name__ == "__main__":
    generate()
