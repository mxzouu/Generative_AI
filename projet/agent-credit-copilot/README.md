# 💳 Credit Copilot — Agent IA d'aide à la décision de crédit

Assistant IA pour un **conseiller crédit** : il centralise le score de risque (ML), l'explication
du score (SHAP), la doc réglementaire interne (RAG, réponses sourcées PDF + page) et l'historique
client — via un chatbot. **L'agent ne décide jamais** : c'est le conseiller qui accepte, refuse ou
escalade, et sa décision est journalisée.

Stack : boucle agent Claude Haiku (reason → act → observe) ↔ serveur **MCP** (stdio) ↔ SQLite +
modèle **XGBoost/SHAP** + index **ChromaDB** (RAG), exposée via une **API FastAPI** + un front
statique (`web/`).

---

## 1. Architecture

```
web/ (HTML/JS/CSS)  ──HTTP──►  app/web_server.py (FastAPI, port 8600)
                                    │
                                    ├─ endpoints directs : pile de dossiers, score, SHAP, décision, PDF
                                    ├─ /api/chat ─────────►  app/agent.py (boucle Haiku)
                                    │                              │  session MCP stdio (spawn)
                                    │                              ▼
                                    │                     app/credit_server.py (serveur MCP, 14 tools)
                                    │                              ├─ SQLite   data/credit_copilot.db
                                    │                              ├─ ML       models/credit_model.joblib (XGBoost + SHAP)
                                    │                              └─ RAG      chroma_index/ (PDF découpés page par page)
                                    └─ app/mailer.py (rédaction Haiku + envoi SMTP des courriers, avec simulation si pas de mot de passe)
```

---

## 2. Prérequis

- Python **3.11+**
- Une clé API Anthropic (`ANTHROPIC_API_KEY`)
- (optionnel) un mot de passe d'application Gmail pour l'envoi réel des emails — sans lui, les
  emails sont juste journalisés dans `data/outbox.log` (mode simulation, rien n'est cassé)

---

## 3. Installation

```bash
cd agent-credit-copilot

python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate

pip install -r app/requirements.txt
```

Copie le modèle `.env.example` en `.env` à la racine du projet, puis remplis ta clé :

```bash
cp .env.example .env        # Windows : copy .env.example .env
```

```env
ANTHROPIC_API_KEY=sk-ant-...

# optionnel — sinon les emails partent en simulation (data/outbox.log)
SMTP_USER=ton_adresse@gmail.com
SMTP_APP_PASSWORD=xxxxxxxxxxxxxxxx
```

> Le `.env` est gitignoré : ta clé n'est jamais committée.

---

## 4. Générer les données, le modèle et l'index (à faire une fois)

Le zip ne contient **ni** la base SQLite, **ni** le modèle entraîné, **ni** l'index ChromaDB (ils
sont gitignorés, régénérables). Il faut lancer ces scripts **dans cet ordre**, depuis la racine du
projet :

```bash
python scripts/generate_sqlite_db.py       # 1. base clients/dossiers synthétique (Faker, seedée)
python scripts/generate_training_csv.py    # 2. CSV d'entraînement dérivé de la base
python ml/train.py                         # 3. entraîne + sauvegarde models/credit_model.joblib
python scripts/generate_pdfs.py            # 4. génère les 6 PDF de procédures internes (data/docs/)
python scripts/build_chroma_index.py       # 5. indexe les PDF dans ChromaDB (chroma_index/)
python scripts/generate_demo_scenarios.py  # 6. sélectionne 4 dossiers types pour la démo
```

(Optionnel) vérifier que la boucle agent fonctionne de bout en bout sans passer par l'UI :

```bash
python scripts/smoke_test_agent.py DOS0031
```

---

## 5. Lancer l'app

```bash
uvicorn app.web_server:app --app-dir . --port 8600
```

→ ouvre **http://localhost:8600**

---

## 6. Ce qu'il y a dedans

```
agent-credit-copilot/
├── app/
│   ├── agent.py            # boucle agent Haiku : reason → act → observe (system prompt = SKILL.md)
│   ├── credit_server.py    # serveur MCP (FastMCP, stdio) : 13 tools — accès exclusif aux données
│   ├── web_server.py       # backend FastAPI (API REST + sert web/) — l'UI
│   ├── mailer.py           # rédaction (Haiku) + envoi SMTP des emails, avec fallback simulation
│   └── requirements.txt
├── ml/
│   ├── features.py         # définition des features (source unique de vérité train/serving)
│   ├── context.py          # BDD → contexte features (par client ou par dossier)
│   ├── model.py            # CreditModel : XGBoost + explication SHAP (TreeExplainer)
│   └── train.py            # entraîne et persiste le modèle
├── scripts/                 # génération des données/artefacts (voir §4) + smoke test
├── skills/credit_review/SKILL.md   # le system prompt / SOP de l'agent
├── data/
│   ├── docs/                # les 6 PDF réglementaires internes (générés)
│   ├── credit_copilot.db    # SQLite (généré, gitignoré)
│   └── outbox.log           # journal des emails simulés
├── web/                     # front HTML/JS/CSS de l'UI
└── models/, chroma_index/   # artefacts générés (gitignorés)
```

**Les 14 tools MCP exposés par `credit_server.py`** (détail complet dans
`skills/credit_review/SKILL.md`) :

| Tool | Rôle |
|---|---|
| `get_client_profile` | profil client |
| `run_credit_score` | score ML (probabilité de défaut + bande de risque) |
| `explain_score` | facteurs SHAP de la prédiction |
| `search_internal_docs` | RAG sur la doc interne, réponse sourcée (PDF + page) |
| `query_client_history` | historique crédits / incidents |
| `simulate_offer` | re-scoring "what-if" (autre montant/durée/apport) |
| `propose_counter_offer` | fige une contre-offre (après itération sur `simulate_offer`) |
| `request_decision` | ouvre le courrier de décision dans l'UI (équivaut au clic bouton) |
| `flag_decision_review` | **garde-fou** : verdict de la revue autonome d'une décision (warnings) |
| `record_decision` | écrit la décision en base (n'écrit que sur ordre explicite du conseiller) |
| `add_client`, `add_dossier` | créer un client / un dossier |
| `reopen_dossier` | remettre un dossier "en cours" |
| `list_dossiers` | lister la pile par statut |

**Deux garde-fous clés :**
- Sous le seuil critique de risque, `run_credit_score` lève `no_auto_processing` → escalade
  obligatoire, jamais de décision automatique.
- **Revue de décision agentique** : avant de finaliser une décision, l'agent **étudie le dossier en
  autonomie** (score + SHAP + historique + grille via RAG) et lève des **warnings sourcés** si la
  décision est incohérente (`flag_decision_review`) — le conseiller peut passer outre, mais informé.

## Debug mode (exigé)

L'UI expose le travail de l'agent **en temps réel** : raisonnement (chain of thought) + chaque tool
appelé avec ses arguments et son résultat, dans le chatbot comme dans la revue de décision. Un
interrupteur **🧠 Raisonnement** (en haut à droite) permet de l'afficher ou de le masquer.

---

## 7. Dépannage rapide

- **`ModuleNotFoundError`** → l'environnement virtuel n'est pas activé ou `pip install` pas relancé.
- **Le chatbot ne répond pas / erreur côté agent** → vérifie que `ANTHROPIC_API_KEY` est bien dans
  `.env` à la racine du projet.
- **`credit_model.joblib` introuvable** → relance §4 dans l'ordre (surtout `ml/train.py`).
- **Le RAG ne trouve rien** → `chroma_index/` vide ou absent → relance
  `scripts/generate_pdfs.py` puis `scripts/build_chroma_index.py`.
- **Emails jamais envoyés pour de vrai** → normal sans `SMTP_APP_PASSWORD` (mode simulation,
  regarde `data/outbox.log`).