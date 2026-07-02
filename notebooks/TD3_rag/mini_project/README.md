# Mini-project — Fnac-style catalog chatbot

A minimal Flask web app that answers questions about the product catalog, grounded in retrieval
(the `retrieve -> answer` loop from TD3 §7).

## Setup

From this folder (`notebooks/TD3_rag/mini_project/`):

```bash
pip install -r requirements.txt
```

Make sure `ANTHROPIC_API_KEY` is set in the `.env` file at the project root (same one used by the
notebook).

## Run

```bash
python build_index.py   # once — builds the persistent ChromaDB index in ./chroma_db
python app.py            # starts the app on http://127.0.0.1:5000
```

Re-run `build_index.py` whenever `data/products.csv` changes.

## How it works

- `build_index.py` embeds every product (`all-MiniLM-L6-v2`, same model as the notebook) and stores
  the vectors in a **persistent** ChromaDB collection on disk (`chroma_db/`), instead of the
  notebook's in-memory client.
- `app.py` loads that index at startup and exposes:
  - `GET /` — a single-page UI with a text box.
  - `POST /ask` — takes `{"question": "..."}`, retrieves the `k` most relevant products, and asks
    Haiku (`claude-haiku-4-5`) to answer grounded only in those products.
