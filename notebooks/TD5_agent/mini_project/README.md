# Mini-project — PIM Copilot

A small chat web-app: paste a messy supplier blurb, watch the agent categorize it, fill every
attribute (`null` where unknown), route leftovers to `extra`, and create the product — then see it
appear in the Light PIM viewer. It's your own Claude Desktop, but for the PIM.

It reuses your earlier bricks: the **TD4 MCP server** (the toolbox, over **stdio**) and the **TD3 RAG**
(reached through `search_products`). The agent loop is the one you wrote in the TD5 notebook.

## Architecture

```
 browser (Vue chat UI)
    │  POST /api/chat  { messages }
    ▼
 FastAPI backend  (app/main.py)
    │  run_agent loop + Haiku + add_product skill   (app/agent.py)
    │  MCP stdio client  ── spawns ──►  TD4 pim_server.py  (subprocess)
    ▼                                        │  writes/reads
 returns { reply, trace }              chroma_store/  (persistent ChromaDB)
                                             ▲
                                             │  reads the SAME index
                                      Light PIM viewer  (notebooks/pim-prod)
```

- **Backend** — `app/main.py` (FastAPI) opens **one** MCP stdio session to the TD4 server at startup
  and exposes `POST /api/chat`, which runs the agent loop and returns the reply **plus the tool-call
  trace**. The agent itself is `app/agent.py`.
- **Reuse of TD4** — the backend never re-implements the tools; it just points a stdio client at
  `notebooks/TD4_mcp/mini_project/pim_server.py` (that server was extended to carry `extra`). By
  default the spawned python is the **same interpreter running the backend**, so launching from the
  repo venv reuses all deps.
- **Frontend** — `web/` is a no-build Vue 3 app (vendored) served by the same FastAPI process.
- **PIM viewer** — `notebooks/pim-prod` (provided) reads the same on-disk index the TD4 server writes.

## Prerequisites

- The repo venv (`genai_env`) with the deps installed — plus the web deps:
  ```powershell
  .\genai_env\Scripts\python.exe -m pip install -r notebooks\TD5_agent\mini_project\app\requirements.txt
  ```
- An API key: copy `.env.example` to `.env` (here or at the repo root) and set `ANTHROPIC_API_KEY`.
  (The repo root `.env` is picked up automatically, so if your key is already there you're set.)

## Run

Open **three** terminals, all with the venv active (`.\genai_env\Scripts\Activate.ps1`).

**1 · The copilot backend + UI** (from `notebooks/TD5_agent/mini_project/`):
```powershell
uvicorn app.main:app --reload --app-dir . --port 8100
# open http://localhost:8100
```
The backend spawns the TD4 server for you — you don't launch `pim_server.py` yourself. First start is
a few seconds (it loads the embedding model and opens the index).

**2 · The Light PIM viewer** (from `notebooks/pim-prod/`), pointed at the TD4 store:
```powershell
$env:PIM_INDEX_DIR = "..\TD4_mcp\mini_project\chroma_store"
uvicorn app.main:app --reload --app-dir . --port 8000
# open http://localhost:8000
```
(Or start it without the env var and use the **Index** picker in the header to select
`notebooks/TD4_mcp/mini_project/chroma_store`.)

## The payoff loop

1. In the copilot (`:8100`), click **"Enrich a messy supplier blurb"** (or paste your own).
2. Watch the trace: `get_category_tree → get_category_attributes → search_products → create_product`.
3. Refresh the PIM viewer (`:8000`) → the new product is there, fully attributed, with its `extra` payload.
4. Back in the copilot, ask *"what noise-cancelling headphones do we carry?"* → it comes back in search,
   seconds after creation, no reindex.

## Notes

- **`extra`** — the TD4 server was extended (in `pim_server.py`) to accept and store `extra` in the
  three usual places (create, seed metadata, parse-back). If your `chroma_store/` was built before that
  change, delete the folder once so it rebuilds with the `extra` field on the next backend start.
- **No API key in code** — it comes from `.env` only.
- **One shared MCP session** — `/api/chat` serializes turns with a lock (fine for a single-user POC).
- **Going further** — a *propose → confirm* step before the write, a second skill (`update_price`), or
  streaming the trace token-by-token.
