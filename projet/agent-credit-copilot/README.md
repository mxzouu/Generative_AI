# 💳 Credit Copilot — Agent IA d'aide à la décision de crédit

> **Projet du cours *Generative AI M2 Apprentissage 2026*.**
> Un agent IA qui assiste un **conseiller crédit** dans l'étude d'un dossier — sans jamais décider à sa
> place — en réutilisant les briques des TD1 → TD5 (embeddings, classification, RAG, MCP, boucle agent).
> C'est le **jumeau du projet `agent-detection-fraude`** : même patron d'architecture (boucle agent Haiku +
> MCP + RAG ChromaDB + modèle ML explicable + human-in-the-loop), transposé au **crédit**, avec une **UI
> Streamlit**, une base **SQLite**, un **RAG sur PDF réglementaires sourcés (fichier + page)** et un
> scoring **XGBoost + SHAP**.

---

## 0. Pour un Claude Code qui découvre ce dépôt

Ce dossier (`projet/agent-credit-copilot/`) est **une spec** : ce README décrit *ce qu'on veut construire*.
Le code sera écrit ensuite, phase par phase (voir §9).

**Ce qui existe déjà dans le dépôt et qu'on réutilise** (chemins relatifs à la racine du repo) :

| Ressource | Chemin | Ce qu'on en tire |
|---|---|---|
| **Le projet jumeau** (le plus important) | `projet/agent-detection-fraude/` | Même architecture. On **copie** `app/agent.py` (boucle agent), le squelette de `app/*_server.py` (MCP FastMCP + ChromaDB), et le patron `ml/` (features / model / train). |
| Template d'agent | `notebooks/TD5_agent/mini_project/` | Boucle `run_agent` + skill dans le system prompt (origine du code de la fraude). |
| Exemple de serveur MCP | `notebooks/TD4_mcp/mini_project/pim_server.py` | Modèle FastMCP + ChromaDB persistant. |
| Environnement Python | `genai_env/` | venv du repo avec `mcp`, `chromadb`, `sentence-transformers`, `anthropic`, `pandas`, `scikit-learn`. **Ajouter : `streamlit`, `xgboost`, `shap`, `pypdf`.** |

**Conventions techniques héritées des TD :**
- Embeddings : `all-MiniLM-L6-v2` (un seul espace vectoriel partagé).
- LLM : **Haiku uniquement** (`claude-haiku-4-5`), appelé dans la boucle agent et le chatbot.
- Stockage RAG : **ChromaDB persistant** sur disque (métadonnées scalaires).
- Transport MCP : **stdio** — l'app *spawn* le serveur MCP en sous-processus et parle sur stdin/stdout.
- Clé API : jamais dans le code, toujours via `.env` (`ANTHROPIC_API_KEY`).

> En une phrase : **c'est le Copilote Fraude, transposé au crédit.** Le « sinistre » devient un « dossier
> client », le « score de fraude » devient une « probabilité de défaut », et l'index RAG ne contient plus
> des sinistres passés mais la **doc réglementaire interne** (politique de crédit, grille de risque).

---

## 1. Le concept

Un **conseiller crédit** doit, pour chaque dossier, croiser quatre choses aujourd'hui **dispersées et
chronophages** : le **score de risque** (modèle), le **dossier client**, la **doc réglementaire interne**
(politique de crédit, grille de risque) et l'**historique** du client. Le Credit Copilot **centralise** tout
ça et **assiste** le conseiller.

Chaque dossier de la pile :
1. l'agent récupère le **profil client** (tool) ;
2. calcule un **score de risque** ML + **probabilité de défaut** (tool) ;
3. **explique** le score en langage clair (feature importances / **SHAP**) (tool) ;
4. répond aux **questions réglementaires** du conseiller via **RAG sur la doc interne**, en **citant la
   source** (PDF + page) (tool) ;
5. rappelle l'**historique** crédits/incidents du client (tool) ;
6. **le conseiller tranche** — accepter / refuser / escalader — et la décision est **enregistrée** (tool),
   ce qui nourrit la base.

Point de design clé : **l'agent recommande, l'humain décide.** Aucune décision de crédit n'est committée
automatiquement. Si le score passe **sous un seuil critique**, l'agent lève un **flag « pas de traitement
auto »** → escalade obligatoire, jamais de décision machine.

---

## 2. Les deux utilisateurs (personas)

- **Le conseiller crédit** (principal) : parcourt la pile de dossiers, lit le score et son explication,
  interroge la doc réglementaire, tranche, enregistre sa décision motivée.
- **Le système / back-office** : alimente la base de dossiers à traiter et conserve la piste d'audit des
  décisions (qui nourrit la base pour la suite).

---

## 3. Architecture (reprend le patron du projet fraude, UI = Streamlit)

```
 Streamlit UI  (streamlit_app.py)
   ├─ Sidebar : pile des dossiers à traiter        (SELECT status='à traiter' dans SQLite)
   ├─ Panneau dossier : profil + score + explication SHAP + bannière seuil critique
   ├─ Chatbot RAG : questions réglementaires        (réponses sourcées PDF + page)
   └─ Décision : Accepter / Refuser / Escalader + justification
        │  appelle  bridge.ask(messages) -> (reply, trace)
        ▼
 CreditAgent  (app/agent.py — boucle Haiku reason→act→observe, copiée de la fraude)
        │  session MCP stdio  ── spawn ──►  serveur MCP crédit (sous-processus)
        ▼                                          │  lit / écrit
 renvoie { reply, trace }                    app/credit_server.py
                                                   ├─ SQLite      data/clients.db   (clients · credit_history · decisions)
                                                   ├─ Modèle ML   models/credit_model.joblib (XGBoost) + SHAP
                                                   └─ ChromaDB    chroma_index/     (chunks PDF réglementaires)
```

- **UI** = Streamlit (synchrone). Elle ne parle jamais MCP directement : elle passe par un **bridge**
  (voir §7) qui garde la session agent/MCP vivante.
- **CreditAgent** = boucle agent + une session MCP stdio ouverte au démarrage ; `run(messages)` renvoie la
  réponse **et la trace des tool calls** (affichée dans un expander pour montrer le raisonnement).
- **Serveur MCP** = la boîte à outils (§5) ; il a l'accès exclusif à SQLite, au modèle et à l'index.

> **Décision d'architecture (comme la §11bis du projet fraude) : le scoring est un modèle ML, pas le LLM.**
> XGBoost produit la probabilité de défaut, SHAP la justifie, Haiku **orchestre** (appelle les tools, croise
> profil / historique / doc, explique en langage naturel) et **l'humain valide**.

---

## 4. Fonctionnalités

### 🎯 MVP (à livrer absolument)
1. **Pile de dossiers** : liste des dossiers `status='à traiter'`, sélection d'un dossier.
2. **Score + probabilité de défaut** par dossier (modèle ML), avec **bande de décision** (faible / à
   examiner / critique).
3. **Explication du score** : top facteurs SHAP de **cette** prédiction, en langage lisible.
4. **Chatbot réglementaire (RAG)** : question en langage naturel → réponse **sourcée (PDF + page)**.
5. **Flag seuil critique** : sous le seuil → bannière « pas de traitement auto, escalade requise ».
6. **Enregistrement de la décision** : Accepter / Refuser / Escalader + justification → écrit en base, le
   dossier passe à `traité`.

### 🚀 Extensions (si le temps le permet — priorité décroissante)
- **Recommandation motivée** : l'agent propose une orientation (« profil à examiner : durée longue + pas
  d'épargne ») que le conseiller confirme ou infirme.
- **Comparaison à la grille** : l'agent confronte automatiquement le score aux seuils de `grille_de_risque`
  et cite la règle applicable.
- **Simulation** : « et si la durée passait de 48 à 24 mois ? » → re-scoring what-if.
- **Historique de décisions** : onglet qui relit la table `decisions` (audit / cohérence des conseillers).
- **Tableau de bord** : répartition des scores, taux d'acceptation, dossiers escaladés.
- **Multi-conseiller** : champ `advisor` + filtrage.

---

## 5. Boîte à outils (les 6 tools MCP)

Le serveur MCP (`app/credit_server.py`, calqué sur `fraud_server.py`) expose exactement ces 6 tools ;
l'agent choisit lesquels appeler et dans quel ordre.

| Tool | Rôle | Nature |
|---|---|---|
| `get_client_profile(client_id)` | Récupère le dossier client (SQLite). | lecture |
| `run_credit_score(client_id)` | Modèle ML → `{ probability_default, decision_band, no_auto_processing }`. | lecture / propose |
| `explain_score(client_id)` | Feature importances / **SHAP** → justification lisible du score. | lecture |
| `search_internal_docs(query, k)` | **RAG** sur la doc interne → texte **+ citation (PDF + page)**. | lecture |
| `query_client_history(client_id)` | Historique crédits / incidents (SQLite). | lecture |
| `record_decision(client_id, decision, rationale)` | Enregistre la décision du conseiller → nourrit la base. | **écriture (seul)** |

**Garde-fous des tools :**
- `run_credit_score` **propose** un score et pose `no_auto_processing: true` si `probability_default ≥ seuil
  critique` — il ne décide jamais.
- `record_decision` est le **seul tool en écriture** ; il n'est appelé **que sur ordre explicite** du
  conseiller (bouton UI ou instruction claire), `decision ∈ {accept, reject, escalate}`, `rationale`
  obligatoire, horodatage → piste d'audit dans la table `decisions`.

> Modèle d'implémentation : `projet/agent-detection-fraude/app/fraud_server.py` (FastMCP + ChromaDB
> persistant + journal de décisions). On garde le même style, on remplace pandas/CSV par **SQLite** et on
> branche **XGBoost + SHAP** au lieu de la régression logistique.

---

## 6. La skill de l'agent

Un fichier `skills/credit_review/SKILL.md` (chargé dans le system prompt), calqué sur
`agent-detection-fraude/skills/triage_claims/SKILL.md`. Il décrit le **SOP** du conseiller :

1. Récupérer le **profil** du dossier (`get_client_profile`).
2. Calculer le **score** (`run_credit_score`) et l'**expliquer** (`explain_score`).
3. Consulter l'**historique** (`query_client_history`) si pertinent.
4. Pour toute **question réglementaire**, interroger la doc (`search_internal_docs`) et **toujours citer la
   source (PDF + page)** — ne jamais inventer une règle.
5. Si `no_auto_processing` est levé → **le dire clairement** : pas de traitement automatique, escalade.
6. **Ne jamais enregistrer de décision de sa propre initiative** : `record_decision` uniquement quand le
   conseiller a explicitement tranché.
7. Rester factuel et prudent : l'agent **assiste**, il ne conclut pas à la place de l'humain.

---

## 7. ⚠️ Points critiques

### 7.1 Les données (priorité n°1, avant le code)

La démo ne « marche » que si les données sont crédibles. Trois sources à préparer, **découplées** (on peut
changer de dataset sans toucher au reste — comme la fraude : remplacer le fichier source puis relancer
l'ingestion suffit) :

**(a) Dataset ML → base clients.** *(Choix du dataset à trancher plus tard.)* Recommandation :
**German Credit (Statlog)** — 1000 clients, 20 attributs, label `good/bad`, petit et propre, idéal pour
SHAP et une démo. Alternative envisagée : **Home Credit** (beaucoup plus lourd : 300k lignes, 200+ features,
jointures multi-tables). **Chaque ligne du dataset = un client.** C'est ce qui unifie tout : base clients +
matrice de features + entraînement du modèle proviennent de la même source.

**(b) SQLite `data/clients.db`** — 3 tables :
- `clients` : `client_id`, les features du dataset (âge, montant demandé, durée, historique de compte,
  emploi, épargne…), `status ∈ {'à traiter', 'traité'}`.
- `credit_history` : `client_id`, crédits passés, incidents / retards de paiement — **quelques clients avec
  des incidents plantés exprès** pour que l'historique raconte quelque chose en démo.
- `decisions` : `client_id`, `decision`, `rationale`, `advisor`, `at` — la piste d'audit alimentée par
  `record_decision`.

**(c) Doc réglementaire interne (PDF)** — à **écrire** (2-3 PDF courts) : `politique_credit.pdf`,
`grille_de_risque.pdf`, éventuellement `procedure_escalade.pdf`. Contenu : seuils d'acceptation, règles par
bande de risque, taux maximum, conditions d'escalade obligatoire, pièces exigées… **Ces PDF doivent contenir
les réponses aux questions posées en démo** (ex. « quel taux max pour un risque élevé ? » doit exister dans
un PDF, à une page précise, pour que la citation soit vérifiable).

Livrables données : `data/build_data.py` (dataset → `clients.db` + historique synthétisé) et les PDF sous
`data/docs/` (écrits à la main ou générés depuis du Markdown).

### 7.2 Le pont async ↔ Streamlit

Streamlit est **synchrone** ; la session MCP (`ClientSession`) est **async**. Le patron robuste :

> Un objet **`AgentBridge`** (`app/bridge.py`) qui possède **son propre event loop dans un thread de fond**,
> garde la session MCP stdio **ouverte** pour toute la durée de vie de l'app, et expose une méthode **sync**
> `ask(messages) -> (reply, trace)`. On le crée **une seule fois** via `@st.cache_resource` (partagé entre
> les reruns Streamlit). L'UI n'appelle jamais `await` — seulement `bridge.ask(...)`.

C'est la principale différence de plomberie avec le projet fraude (qui, lui, exposait la boucle via FastAPI
et n'avait donc pas ce souci). Le reste de la boucle agent (`app/agent.py`) est **copié tel quel**.

---

## 8. Le modèle ML + SHAP (`ml/`)

Même contrat que le `FraudModel` du projet jumeau, moteur **XGBoost** :

- `ml/features.py` : `engineer(df)` → matrice de features indexée par `client_id` ; encodage des variables
  catégorielles **constant entre entraînement et serving** (comme la fraude). Expose `FEATURES` et
  `FEATURE_LABELS` (libellés lisibles pour l'explication).
- `ml/model.py` : `CreditModel` avec `train(df)` (`XGBClassifier`), `predict_proba`, `explain` (**SHAP
  `TreeExplainer`** → contribution de chaque feature à **cette** prédiction, pas des importances globales),
  `score()` → `{ probability_default, decision_band, top_factors, no_auto_processing }`, `save` / `load`
  (joblib, avec vérification que les features persistées correspondent).
- `ml/train.py` : entraîne + persiste `models/credit_model.joblib` (métriques : AUC, n_train). Le serveur
  MCP entraîne au premier lancement si le modèle manque (comme la fraude).
- **Bandes de décision** (seuils configurables) :
  `P(défaut) ≥ 0.75` → **critique** (`no_auto_processing = true`) ; `0.40–0.75` → **à examiner** ;
  `< 0.40` → **faible risque**.

SHAP `TreeExplainer` est quasi instantané sur XGBoost → aucune latence problématique en démo.

---

## 9. Structure de fichiers (état réel)

> ✅ = déjà construit et validé · 🚧 = squelette fonctionnel à enrichir. Voir aussi
> [`data/README.md`](data/README.md) pour le catalogue des données générées.

```
projet/agent-credit-copilot/
├── README.md                       # ce fichier
├── streamlit_app.py                # 🚧 UI Streamlit : pile → score → chatbot → décision
├── app/
│   ├── __init__.py
│   ├── agent.py                    # ✅ boucle CreditAgent (copie de la fraude, renommée)
│   ├── credit_server.py            # ✅ serveur MCP : les 6 tools du §5 (testés)
│   ├── bridge.py                   # ✅ AgentBridge : event loop async en thread + ask() sync (§7.2)
│   └── requirements.txt            # deps du projet
├── skills/
│   └── credit_review/SKILL.md      # ✅ le SOP de l'agent
├── ml/
│   ├── features.py                 # ✅ FEATURES, compute_features (source unique de vérité)
│   ├── context.py                  # ✅ BDD → ctx (ctx_from_credit / ctx_from_demande)
│   ├── model.py                    # ✅ CreditModel (XGBoost + SHAP)
│   └── train.py                    # ✅ entraîne + persiste models/credit_model.joblib
├── scripts/
│   ├── generate_sqlite_db.py       # ✅ synthèse de credit_copilot.db (Faker, seedé)
│   ├── generate_training_csv.py    # ✅ CSV dérivé de la base (cohérence garantie)
│   ├── generate_pdfs.py            # ✅ 6 PDF (reportlab, pieds de page numérotés)
│   ├── build_chroma_index.py       # ✅ PDF → chunks page-à-page → ChromaDB
│   └── generate_demo_scenarios.py  # ✅ 4 dossiers de démo scorés
├── data/
│   ├── README.md                   # catalogue des données
│   ├── credit_copilot.db           # ✅ SQLite (gitignoré, régénérable)
│   ├── credit_scoring_dataset.csv  # ✅ (gitignoré, régénérable)
│   ├── demo_scenarios.json         # ✅ (gitignoré, régénérable)
│   └── docs/                       # ✅ 6 PDF de procédures internes
├── models/credit_model.joblib      # ✅ (gitignoré, régénérable) — AUC test ≈ 0.88
├── chroma_index/                   # ✅ index ChromaDB persistant (gitignoré)
└── .env.example
```

**Reste à faire (phases 5→8) :** brancher la clé API dans `.env`, tester la boucle agent en
conditions réelles, et finaliser l'UI Streamlit (le fichier tourne mais n'a pas été exécuté
end-to-end avec l'API).

---

## 10. Plan de construction (ordre conseillé)

1. **Données (bloc critique, §7.1)** : `build_data.py` (dataset → SQLite + historique piégé) + écrire les
   PDF réglementaires. *Rien ne marche sans ça.*
2. **ML** : `features.py` → `model.py` (XGBoost + SHAP) → `train.py`. Vérifier l'AUC et que `explain` sort
   des facteurs sensés.
3. **RAG** : `ingest_docs.py` → index ChromaDB ; tester une requête → bonnes citations (PDF + page).
4. **Serveur MCP** : les 6 tools, testés un par un en isolation.
5. **Boucle agent** : copier `agent.py` + écrire `SKILL.md` ; tester en CLI avec des `messages` en dur.
6. **Bridge** : `bridge.py` (event loop en thread) + `@st.cache_resource`.
7. **UI Streamlit** : sidebar (pile) → panneau dossier (score + SHAP + bannière critique) → chatbot RAG
   (avec expander sources + expander trace) → boutons décision.
8. **Fil de démo** de bout en bout + garde-fous (`max_iters`, seuil critique, `record_decision` sur ordre
   explicite uniquement).

---

## 11. Scénario de démo (le fil narratif)

1. Le conseiller ouvre l'app : la **pile** de dossiers à traiter s'affiche dans la sidebar.
2. Il **sélectionne un dossier** → profil + **score calculé** (ex. `P(défaut)=0.62`, bande « à examiner »).
3. L'**explication SHAP** s'affiche : « durée du crédit longue + absence d'épargne pèsent le plus ».
4. Il **interroge le chatbot** : *« pour un dossier à ce niveau de risque, quel taux maximum ? »* →
   réponse **sourcée** *(grille_de_risque.pdf, p.3)*.
5. Il **tranche** (Accepter / Refuser / Escalader) + justification → **`record_decision`** → le dossier
   passe à « traité ».
6. (Cas critique) Un dossier sous le seuil affiche la **bannière rouge « pas de traitement auto »** →
   escalade obligatoire, aucune décision machine.

---

## 12. Garde-fous & éthique (à mettre en avant — ça valorise le projet)

- **Human-in-the-loop obligatoire** : aucune décision de crédit committée sans validation du conseiller ;
  `record_decision` est le seul tool en écriture et n'est appelé que sur ordre explicite.
- **Seuil critique = pas de traitement auto** : sous le seuil, escalade forcée, jamais de décision machine.
- **Explicabilité** : score justifié par SHAP (facteurs de *cette* décision) + doc réglementaire **citée
  (PDF + page)** → pas de boîte noire.
- **`max_iters`** dans la boucle agent (garde-fou anti-boucle infinie).
- **Cadrage honnête** : outil d'**aide à la décision** (ML + RAG + LLM), pas un système d'octroi automatique.
  Le conseiller reste le décideur, et la conformité repose sur la doc interne citée, pas sur l'avis du LLM.

---

## 13. Correspondance avec les TD (à citer en soutenance)

- **TD1** — embeddings MiniLM : l'espace vectoriel qui rapproche une question réglementaire du bon passage.
- **TD2** — classification : le scoring crédit (XGBoost, `good/bad` → probabilité de défaut).
- **TD3** — RAG : retrouver la règle applicable dans la doc interne, avec sa source.
- **TD4** — MCP : le serveur qui expose les 6 tools de l'agent (transport stdio).
- **TD5** — boucle agent : reason → act → observe qui orchestre le tout, avec human-in-the-loop.

---

## 14. Démarrage rapide

```powershell
# 1. deps (venv du repo + ajouts du projet)
.\genai_env\Scripts\python.exe -m pip install -r projet\agent-credit-copilot\app\requirements.txt

# 2. clé API
copy projet\agent-credit-copilot\.env.example projet\agent-credit-copilot\.env  # puis remplir ANTHROPIC_API_KEY

# 3. (re)générer données + modèle + index — depuis projet/agent-credit-copilot/
$py = "..\..\genai_env\Scripts\python.exe"
& $py scripts/generate_sqlite_db.py
& $py scripts/generate_training_csv.py
& $py ml/train.py
& $py scripts/generate_pdfs.py
& $py scripts/build_chroma_index.py
& $py scripts/generate_demo_scenarios.py

# 4. lancer le copilote (depuis projet/agent-credit-copilot/)
..\..\genai_env\Scripts\streamlit.exe run streamlit_app.py   # http://localhost:8501
```

> Les artefacts (`data/*.db`, `.csv`, `models/`, `chroma_index/`) sont **déjà générés** et
> gitignorés. L'étape 3 n'est nécessaire que pour repartir de zéro ou changer le `SEED`.
