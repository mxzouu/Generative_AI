# 🕵️ Agent IA de détection de fraude sur les sinistres

> **Projet de hackathon (12h · binôme)** du cours *Generative AI M2 Apprentissage 2026*.
> Un agent IA qui aide un **conseiller en fraude** à trier les sinistres suspects, en réutilisant
> les briques construites tout au long des TD1 → TD5 (embeddings, classification, RAG, MCP, boucle agent).

---

## 0. Pour un Claude Code qui découvre ce dépôt

Ce dossier (`projet/agent-detection-fraude/`) est **vide au départ** : ce README décrit *ce qu'on veut
construire*. Le code n'existe pas encore — il sera écrit pendant le hackathon.

**Ce qui existe déjà dans le dépôt et qu'on réutilise** (chemins relatifs à la racine du repo) :

| Ressource | Chemin | Ce qu'on en tire |
|---|---|---|
| **Template d'agent** (le plus important) | `notebooks/TD5_agent/mini_project/` | Squelette complet : serveur MCP en stdio + boucle `run_agent` + skill dans le system prompt + front chat Vue. **On part de là.** |
| Exemple de serveur MCP | `notebooks/TD4_mcp/mini_project/pim_server.py` | Modèle de serveur MCP (FastMCP, ChromaDB persistant, tools `search`/`create`/`get`). |
| Dashboard réutilisable | `notebooks/pim-prod/` | App FastAPI + Vue qui **visualise n'importe quel index ChromaDB**. On la repointe sur notre index de sinistres → back-office conseiller quasi gratuit. |
| Données & taxonomie (exemples) | `notebooks/data/` | Format des CSV/JSON et des *skills* (`data/skills/add_product/SKILL.md` = modèle de skill à copier). |
| Environnement Python | `genai_env/` | venv du repo avec `mcp`, `chromadb`, `sentence-transformers`, `anthropic`, `pandas`. Ajouter `fastapi` + `uvicorn`. |

**Conventions techniques héritées des TD :**
- Modèle d'embeddings : `all-MiniLM-L6-v2` (un seul espace vectoriel partagé, TD1 → TD5).
- Modèle LLM : **Haiku uniquement** (`claude-haiku-4-5`), appelé dans la boucle agent.
- Stockage : **ChromaDB persistant** sur disque (métadonnées scalaires → les dicts sont stockés en JSON string).
- Transport MCP : **stdio** — le backend *spawn* le serveur MCP en sous-processus et parle sur stdin/stdout.
- Clé API : jamais dans le code, toujours via un `.env` (`ANTHROPIC_API_KEY`).

> En une phrase : **c'est le PIM Copilot de TD5, transposé à la détection de fraude.** Les « produits »
> deviennent des « sinistres », le « blurb fournisseur » devient un « sinistre du jour à analyser », et
> le « catalogue » devient un « historique de sinistres + fraudes confirmées ».

---

## 1. Le concept

Une compagnie d'assurance reçoit chaque jour des dizaines de **sinistres** (déclarations de dommage :
auto, habitation, etc.). Certains sont **frauduleux** (accident mis en scène, facture gonflée, dommage
fantôme, réseau organisé…). Un **conseiller en fraude** ne peut pas tout éplucher à la main.

**L'agent est un copilote d'aide à la décision.** Chaque matin, le conseiller lui demande :

> « Regarde les sinistres d'hier et dis-moi lesquels sont suspects. »

L'agent :
1. récupère les sinistres de la veille (tool MCP) ;
2. pour chacun, **raisonne** : le compare à l'historique (**RAG**), le **classe** (légitime / suspect /
   frauduleux) et calcule un **score de risque** avec des **signaux explicites** ;
3. renvoie une **file triée** des cas à examiner, chacun avec une **justification sourcée** ;
4. le conseiller **valide ou rejette** chaque cas (human-in-the-loop), et peut **demander des infos
   supplémentaires** (« montre-moi l'historique de ce client », « réclame la facture de réparation »).

Point de design clé : **l'agent suggère, l'humain décide.** Le label « fraude » ne se commit jamais
automatiquement. C'est un outil d'aide à la décision, pas un juge automatique.

---

## 2. Les deux utilisateurs (personas)

- **Le conseiller en fraude** (principal) : reçoit le briefing matinal, examine les cas priorisés,
  demande des approfondissements, valide/rejette, déclenche des demandes de pièces.
- **Le système / back-office** : alimente la base de sinistres (nouveaux sinistres du jour) et conserve
  l'historique des fraudes confirmées (qui sert d'exemples pour le RAG).

---

## 3. Architecture (reprend le patron TD5)

```
 Navigateur — Chat conseiller (Vue, sans build)
    │  POST /api/chat  { messages }
    ▼
 Backend FastAPI  (app/main.py)
    │  boucle run_agent + Haiku + skill "triage_claims"   (app/agent.py)
    │  client MCP stdio ── spawn ──►  serveur MCP fraude  (app/fraud_server.py, sous-processus)
    ▼                                         │  lit / écrit
 renvoie { reply, trace }             chroma_index/  (ChromaDB persistant : sinistres + fraudes confirmées)
                                              ▲
                                              │  lit le MÊME index
                                       Dashboard sinistres  (réutilise notebooks/pim-prod)
```

- **Backend** = boucle agent + une session MCP stdio ouverte au démarrage. Endpoint `POST /api/chat`
  qui renvoie la réponse **et la trace des tool calls** (pour l'afficher en direct).
- **Serveur MCP** = la « boîte à outils » de l'agent (voir §5). Il possède l'accès exclusif à l'index.
- **Front** = chat qui montre le raisonnement de l'agent + une vue « file des cas suspects ».
- **Dashboard** = `pim-prod` repointé sur `chroma_index/` pour parcourir les sinistres.

---

## 4. Fonctionnalités

### 🎯 MVP (à livrer absolument dans les 12h)
1. **Briefing matinal** : `« analyse les sinistres du <date> »` → file triée des cas suspects, une ligne
   de justification chacun.
2. **Classification + score de risque** par sinistre (légitime / suspect / frauduleux + score 0–100).
3. **Explication sourcée** : les signaux déclencheurs **et** les sinistres passés similaires (RAG).
4. **Approfondissement en langage naturel** : `« pourquoi #4573 ? »`, `« historique de ce client ? »`.
5. **Validation humaine** : le conseiller marque `fraude confirmée` / `faux positif` (tool).

### 🚀 Extensions (si le temps le permet — priorité décroissante)
- **Demande de pièces** comme tool : `request_document('facture')`, `request_document('constat')` (loggé).
- **Boucle d'apprentissage** : un cas validé « fraude confirmée » est ré-indexé comme **exemple étiqueté**
  → il ressort dans le RAG des analyses suivantes (le « moment fraîcheur » de TD3/TD5, version fraude).
- **Détection de réseaux (rings)** : relier des sinistres d'assurés *différents* partageant un même
  RIB/téléphone/adresse → « ces 3 sinistres pointent le même IBAN ».
- **Typologie de fraude** : accident mis en scène, gonflage de facture, dommage fantôme, usurpation…
- **Incertitude calibrée** : distinguer les cas *évidents* des *borderline* (montrés séparément).
- **Rapport d'enquête auto** : pour un cas confirmé, l'agent rédige un résumé prêt à transmettre.
- **Escalade** vers un enquêteur (tool) + **piste d'audit** de chaque décision (conformité).
- **Coût du faux positif** : afficher les borderline à part, seuil ajustable.

---

## 5. Boîte à outils (tools MCP)

Le serveur MCP expose ces tools (l'agent choisit lesquels appeler, dans l'ordre qu'il décide) :

| Tool | Rôle |
|---|---|
| `get_claims(date)` | Liste les sinistres d'une date (le briefing matinal). |
| `get_claim(claim_id)` | Détail complet d'un sinistre. |
| `get_customer_history(customer_id)` | Tous les sinistres passés d'un assuré. |
| `search_similar_claims(query, k)` | RAG : sinistres passés sémantiquement proches (dont fraudes confirmées). |
| `find_shared_identifiers(claim_id)` | Autres sinistres partageant RIB / tél / adresse (détection de rings). |
| `request_document(claim_id, doc_type)` | Enregistre une demande de pièce au client. |
| `flag_claim(claim_id, score, reason)` | Marque un sinistre comme suspect (proposition, pas décision). |
| `validate_case(claim_id, verdict)` | Décision du conseiller : `fraud_confirmed` / `false_positive`. |

> Modèle d'implémentation : `notebooks/TD4_mcp/mini_project/pim_server.py` (FastMCP + ChromaDB persistant).

## 6. La skill de l'agent

Un fichier `skills/triage_claims/SKILL.md` (chargé dans le system prompt), calqué sur
`notebooks/data/skills/add_product/SKILL.md`. Il décrit le **SOP** de l'agent :

1. Récupérer les sinistres du jour (`get_claims`).
2. Pour chaque sinistre : lire les détails, récupérer l'historique client, chercher des cas similaires
   et des identifiants partagés.
3. Évaluer les **signaux de risque** (voir §7), attribuer un **score** et une **typologie**.
4. **Ne jamais accuser** : produire une *suspicion justifiée*, avec les preuves et les cas de référence.
5. Trier par score décroissant et présenter la file au conseiller.
6. N'appeler `flag_claim` que sur les cas au-dessus d'un seuil ; laisser la validation à l'humain.

---

## 7. ⚠️ Le point le plus critique : la donnée synthétique

**Ce projet ne « marche » en démo que si les données contiennent des fraudes détectables.** C'est la
**priorité n°1**, avant même le code.

Il faut un **générateur de dataset** (`data/generate_claims.py`) qui produit ~150–300 sinistres, dont
**~10 % piégés** avec des signaux volontairement plantés :

- montant **aberrant** vs la norme de la catégorie ;
- sinistre déclaré **juste après la souscription** ;
- **RIB / téléphone / adresse partagés** entre assurés différents (un « ring ») ;
- **doublon** du même dommage sur deux polices ;
- **incohérences de dates** (incident avant la couverture, week-end/jour férié) ;
- montants **ronds**, descriptions vagues, réclamations répétées du même assuré.

Prévoir aussi un lot de **fraudes confirmées historiques** (étiquetées) → elles peuplent l'index et
servent de références au RAG (« ce mode opératoire correspond à une fraude confirmée l'an dernier »).

Format suggéré (CSV → indexé dans ChromaDB, texte embarqué = description du sinistre) :
`claim_id, date, customer_id, policy_id, type, amount, incident_date, policy_start, iban, phone, address, description, label`.

---

## 8. Garde-fous & éthique (à mettre en avant — ça valorise le projet)

- **Human-in-the-loop obligatoire** : aucun label « fraude » committé sans validation du conseiller.
- **Explicabilité** : tout flag est justifié par des signaux + des cas de référence (pas de boîte noire).
- **`max_iters`** dans la boucle + aucune action automatique côté client.
- **Coût du faux positif** : flaguer un client honnête est coûteux → seuil prudent, cas borderline à part.
- **Cadrage honnête** : outil d'**aide à la décision** (LLM + RAG + règles), pas un modèle de fraude
  entraîné en production. Le conseiller reste le décideur.

---

## 9. Structure de fichiers cible (à construire pendant le hackathon)

```
projet/agent-detection-fraude/
├── README.md                  # ce fichier
├── app/
│   ├── __init__.py
│   ├── agent.py               # boucle run_agent + client MCP stdio (cf. TD5 mini_project)
│   ├── fraud_server.py        # serveur MCP : les tools du §5 (cf. TD4 pim_server.py)
│   ├── main.py                # FastAPI : POST /api/chat, sert le front
│   └── requirements.txt
├── web/                       # front chat Vue (sans build, cf. TD5 mini_project/web)
│   ├── index.html · app.js · styles.css
│   └── vendor/vue.global.prod.js
├── skills/
│   └── triage_claims/SKILL.md # le SOP de l'agent (cf. data/skills/add_product)
├── data/
│   ├── generate_claims.py     # générateur de sinistres piégés (PRIORITÉ 1)
│   └── claims.csv             # dataset généré (regénérable, gitignoré)
├── chroma_index/              # index ChromaDB persistant (gitignoré)
└── .env.example
```

---

## 10. Démarrage rapide (une fois le code écrit)

```powershell
# 1. deps
.\genai_env\Scripts\python.exe -m pip install -r projet\agent-detection-fraude\app\requirements.txt

# 2. clé API
copy projet\agent-detection-fraude\.env.example projet\agent-detection-fraude\.env  # puis remplir ANTHROPIC_API_KEY

# 3. générer le dataset piégé + construire l'index
.\genai_env\Scripts\python.exe projet\agent-detection-fraude\data\generate_claims.py

# 4. lancer le copilote (depuis projet/agent-detection-fraude/)
uvicorn app.main:app --reload --app-dir . --port 8100   # http://localhost:8100

# 5. (option) dashboard sinistres : pim-prod repointé sur notre index
#    depuis notebooks/pim-prod/ :
$env:PIM_INDEX_DIR = "..\..\projet\agent-detection-fraude\chroma_index"
uvicorn app.main:app --reload --app-dir . --port 8000   # http://localhost:8000
```

---

## 11. Scénario de démo (le fil narratif)

1. Le conseiller ouvre le chat : *« Bonjour, analyse les sinistres du 6 juillet. »*
2. L'agent affiche sa trace (`get_claims → get_customer_history → search_similar_claims → find_shared_identifiers`)
   puis : *« 47 sinistres hier, 5 méritent ton attention. »* — file triée par score.
3. Le conseiller : *« Pourquoi le #4573 ? »* → l'agent détaille les signaux + 2 fraudes passées similaires.
4. *« Réclame la facture de réparation. »* → tool `request_document`, demande loggée.
5. Le conseiller **valide** la fraude → le cas devient un exemple de référence, et un rapport est rédigé.
6. On rafraîchit le dashboard → le sinistre apparaît marqué, avec son score et son historique.

---

## 11 bis. Décision d'architecture (mise à jour hackathon) : le scoring est un modèle ML

Différence avec le concept initial : la détection « frauduleux ou non » est faite par un
**modèle ML léger** (`ml/` : LogisticRegression `class_weight='balanced'` + StandardScaler),
PAS par le LLM. Répartition des rôles :

- le **modèle ML** score chaque sinistre à partir de ~13 features tabulaires (signaux du §7)
  et **explique chaque prédiction** : contribution exacte = coefficient × valeur standardisée
  → tool MCP `score_claim(id)` → `{ probability, risk_band, top_factors }` (+ `score_claims(date)`
  en batch pour le briefing) ;
- l'**agent LLM (Haiku, boucle TD5)** orchestre : scoring via MCP, contexte (historique client,
  RAG, identifiants partagés), explication en langage naturel, et **l'humain valide**.

Pipeline : `data/generate_claims.py` (stub synthétique, à remplacer par le vrai dataset) →
`ml/train.py` (entraîne + persiste `models/fraud_model.joblib`) → `app/fraud_server.py`
(charge le modèle au démarrage, l'entraîne s'il manque). L'ingestion des données reste
découplée : remplacer `claims.csv` puis relancer `ml/train.py` suffit.

---

## 12. Correspondance avec les TD (à citer dans la soutenance)

- **TD1** — embeddings MiniLM : l'espace vectoriel qui rend deux sinistres « proches ».
- **TD2** — classification : légitime / suspect / frauduleux + typologie.
- **TD3** — RAG : retrouver les sinistres passés et fraudes confirmées similaires.
- **TD4** — MCP : le serveur qui expose les tools de l'agent.
- **TD5** — boucle agent : reason → act → observe qui orchestre le tout, avec human-in-the-loop.
