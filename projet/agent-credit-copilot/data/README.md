# 📂 Données du Credit Copilot — catalogue

Toutes les données sont **100 % synthétiques** (aucune donnée personnelle réelle) et
**régénérables** via les scripts de `scripts/`. Tout est **seedé (`SEED = 42`)** → reproductible.

## Fichiers produits

| Fichier | Contenu | Généré par |
|---|---|---|
| `credit_copilot.db` | Base SQLite (5 tables + la pile de dossiers) | `scripts/generate_sqlite_db.py` |
| `credit_scoring_dataset.csv` | Jeu d'entraînement du modèle (1 ligne = 1 crédit historique) | `scripts/generate_training_csv.py` |
| `docs/*.pdf` | 6 procédures internes (RAG) | `scripts/generate_pdfs.py` |
| `demo_scenarios.json` | 4 dossiers de démo (accord/analyse/refus/escalade) | `scripts/generate_demo_scenarios.py` |
| `../chroma_index/` | Index vectoriel de la doc (embeddings MiniLM) | `scripts/build_chroma_index.py` |
| `../models/credit_model.joblib` | Modèle XGBoost entraîné | `ml/train.py` |

## 1. Base SQLite — `credit_copilot.db`

Volumes générés : **500 clients · 2 398 crédits historiques (13,2 % en défaut) · 932 incidents ·
988 garanties · 50 demandes** dans la pile · table `decisions` vide (alimentée à l'usage).

| Table | Clé | Colonnes principales |
|---|---|---|
| `clients` | `client_id` (CLI00001…) | nom, prenom, date_naissance, age, situation_familiale, profession, categorie_socio_pro, revenu_mensuel_net, anciennete_emploi_mois, type_contrat, adresse, code_postal, date_creation_compte |
| `credits_historiques` | `credit_id` (CR000001…) | client_id, type_credit (immo/conso/auto/renouvelable), montant, duree_mois, taux, date_debut, date_fin_prevue, statut (en cours/soldé/défaut), mensualite |
| `incidents` | `incident_id` (INC00001…) | client_id, credit_id, date_incident, type (retard/impaye/rejet_prelevement), montant_impaye, nb_jours_retard, regularise |
| `garanties` | `garantie_id` (GAR00001…) | client_id, credit_id, type (hypotheque/nantissement/caution), valeur_estimee, statut |
| **`demandes`** | `demande_id` (DOS0001…) | client_id, type_credit, montant_demande, duree_mois, taux, mensualite_estimee, valeur_garantie_proposee, date_demande, statut (à traiter/traité) |
| `decisions` | `decision_id` (auto) | client_id, demande_id, date_decision, conseiller_id, decision (accord/refus/analyse_manuelle/escalade), score_ml, commentaire, tools_utilises |

> **Ajout par rapport au schéma initial** : la table **`demandes`** = la *pile de dossiers à
> traiter* (nouvelles demandes de crédit). C'est elle qu'affiche le Streamlit, que score
> `run_credit_score(demande_id)` et que clôt `record_decision`. Sans elle, le flux n'avait pas
> d'objet « dossier en cours ».
>
> **Cohérence intégrée** : le risque de défaut est tiré d'un modèle latent (contrat précaire,
> faible ancienneté, endettement élevé, absence de garantie → plus de défauts) et les incidents
> sont générés corrélés au défaut → le modèle apprend des relations métier crédibles.

## 2. Jeu d'entraînement — `credit_scoring_dataset.csv`

2 398 lignes, 11 features + `target` (0 = bon payeur, 1 = défaut). Colonnes :

`age, revenu_mensuel_net, anciennete_emploi_mois, type_contrat_encoded, montant_demande,
duree_mois, taux_endettement, nb_credits_en_cours, nb_incidents_12_mois, nb_jours_retard_max,
ratio_garantie_montant, target`

> **Point critique tenu** (README §7.1) : ces features sont **redérivées de la BDD** via le même
> chemin que le serving (`ml/context.py` → `ml/features.py:compute_features`). Le CSV et le
> vecteur de features d'un dossier réel sont donc **garantis identiques**. Modèle actuel :
> **AUC test ≈ 0.88**.

## 3. Documentation interne — `docs/` (6 PDF)

Chunkés page par page → citations `(fichier.pdf, p.N)`.

1. `politique_octroi_credit.pdf` — critères d'éligibilité, **taux d'endettement max 35 %**, reste à vivre, human-in-the-loop.
2. `grille_scoring_decision.pdf` — **grille PD → bande → recommandation**, seuil critique 75 %.
3. `procedure_credit_immobilier.pdf` — apport, garantie, assurance, durée/taux.
4. `procedure_credit_consommation.pdf` — conso/auto/renouvelable, **délai de rétractation 14 j**.
5. `reglementation_garanties.pdf` — hypothèque/nantissement/caution, décote.
6. `procedure_incidents_impayes.pdf` — types d'incidents, impact score, relance.

> ⚠️ **Version condensée** : ces PDF font 1–2 pages chacun (≈11 chunks au total), pas les 25–40
> pages « réalistes » visées. **Tous les faits nécessaires aux 4 scénarios de démo y sont**, mais
> pour épaissir le corpus (argument « réalisme » du pitch), enrichir le contenu dans
> `scripts/generate_pdfs.py` puis relancer `generate_pdfs.py` + `build_chroma_index.py`.

## 4. Scénarios de démo — `demo_scenarios.json`

Un dossier par cas, avec une question réglementaire suggérée (sollicite les 6 tools en démo) :

| Cas | Dossier | Proba défaut | Recommandation |
|---|---|---|---|
| accord | DOS0015 | ~0.00 | accord |
| analyse manuelle | DOS0036 | ~0.51 | analyse manuelle |
| refus | DOS0031 | ~0.69 | refus |
| escalade | DOS0049 | ~0.99 | refus + `no_auto_processing` (critique) |

## Régénérer toutes les données

```powershell
# depuis projet/agent-credit-copilot/  (interpréteur = venv du repo)
$py = "..\..\genai_env\Scripts\python.exe"
& $py scripts/generate_sqlite_db.py        # 1. base SQLite
& $py scripts/generate_training_csv.py     # 2. CSV (dérivé de la base)
& $py ml/train.py                          # 3. modèle XGBoost
& $py scripts/generate_pdfs.py             # 4. 6 PDF
& $py scripts/build_chroma_index.py        # 5. index ChromaDB
& $py scripts/generate_demo_scenarios.py   # 6. scénarios de démo
```
