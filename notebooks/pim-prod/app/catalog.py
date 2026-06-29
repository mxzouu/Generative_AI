"""ChromaDB access layer for the Light PIM viewer.

This mirrors the helpers from TD4's mini-project reference
(`notebooks/TD4_mcp/mini_project_solution/pim_core.py`) — the embedding model,
the `attributes`-as-JSON-string convention, and ChromaDB as the source of truth —
but is kept **self-contained** so `pim-prod/` works as a standalone bundle.

Unlike the MCP server, the active index here is **mutable**: the UI can point the
viewer at any `chroma_index` folder at runtime (e.g. the one a student's copilot
writes to), so freshly added products show up without restarting anything.
"""
from __future__ import annotations

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

# ── Paths & constants ────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
PIM_PROD = HERE.parent                       # notebooks/pim-prod/
REPO_ROOT = PIM_PROD.parents[1]              # repo root (…/Generative-AI-…)
DATA = PIM_PROD.parent / "data"              # notebooks/data/  (taxonomy lives here)
DEFAULT_INDEX = PIM_PROD.parent / "TD4_mcp" / "mini_project_solution" / "chroma_index"  # the TD4 mini-project catalog
COLLECTION = "catalog"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"        # same MiniLM as TD1→TD4: one shared vector space


# ── Embedding model (lazy: loading it is the slow part of startup) ────────────
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Load the embedding model once, on first use (semantic search / similar)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model


# ── Active index (mutable — switched from the UI) ────────────────────────────
class IndexError_(Exception):
    """Raised when a requested folder is not a usable ChromaDB catalog index."""


class Catalog:
    """Wraps a single ChromaDB `catalog` collection, switchable at runtime."""

    def __init__(self, path: Path | str):
        self.path: Path | None = None
        self._collection = None
        # Boot unbound rather than crashing if the start index is missing/empty
        # (e.g. the TD4 index isn't built yet, or PIM_INDEX_DIR points at a fresh
        # store). The UI's Index picker / POST /api/index can bind one afterwards.
        try:
            self.switch(path)
        except IndexError_ as e:
            print(f"[Light PIM] starting without an index: {e}")

    # -- index selection ------------------------------------------------------
    def switch(self, path: Path | str) -> None:
        """Point the catalog at `path`, validating it holds a `catalog` collection."""
        p = Path(path).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise IndexError_(f"Folder does not exist: {p}")
        try:
            client = chromadb.PersistentClient(path=str(p))
            names = [c.name for c in client.list_collections()]
        except Exception as e:  # corrupt / not-a-chroma dir
            raise IndexError_(f"Not a readable ChromaDB store: {p} ({e})")
        if COLLECTION not in names:
            raise IndexError_(
                f"No '{COLLECTION}' collection in {p}. Found: {names or 'none'}"
            )
        # only swap once everything validated, so a bad path keeps the old index
        self.path = p
        self._collection = client.get_collection(COLLECTION)

    @property
    def collection(self):
        if self._collection is None:
            raise IndexError_(
                "No index loaded. Pick a chroma_index folder (Index picker) or "
                "set PIM_INDEX_DIR, then reload."
            )
        return self._collection

    def info(self) -> dict:
        return {
            "path": str(self.path) if self.path else None,
            "collection": COLLECTION,
            "count": self._collection.count() if self._collection is not None else 0,
        }

    # -- reads ----------------------------------------------------------------
    def all_products(self) -> list[dict]:
        """Every product (metadata + parsed attributes), sorted by SKU."""
        res = self.collection.get(include=["metadatas"])
        products = [
            _to_product(sku, meta)
            for sku, meta in zip(res["ids"], res["metadatas"])
        ]
        products.sort(key=lambda p: p["sku"])
        return products

    def get_product(self, sku: str) -> dict | None:
        got = self.collection.get(ids=[sku], include=["documents", "metadatas"])
        if not got["ids"]:
            return None
        product = _to_product(sku, got["metadatas"][0])
        product["document"] = got["documents"][0]
        return product

    def delete(self, sku: str) -> bool:
        if not self.collection.get(ids=[sku])["ids"]:
            return False
        self.collection.delete(ids=[sku])
        return True

    # -- vector ops -----------------------------------------------------------
    def search(self, query: str, k: int = 12) -> list[dict]:
        """Semantic search: embed the query, return the k nearest products + score."""
        q_vec = get_model().encode(query).tolist()
        k = max(1, min(k, self.collection.count()))
        res = self.collection.query(query_embeddings=[q_vec], n_results=k)
        return _hits_with_scores(res)

    def similar(self, sku: str, k: int = 5) -> list[dict]:
        """Nearest neighbours of an existing product (by its own embedding).

        We re-embed the product's `document` rather than fetching its stored
        vector via `get(include=["embeddings"])`. This viewer is a long-lived
        read-only process; when another process (e.g. a TD5 copilot) adds a
        product, our handle's metadata reads see it (shared SQLite) but our
        in-memory HNSW vector segment is stale, so a vector lookup for that SKU
        raises "Error finding id". Re-embedding the doc with the same MiniLM
        model yields the identical vector and sidesteps that stale lookup.
        """
        got = self.collection.get(ids=[sku], include=["documents"])
        if not len(got["ids"]):
            return []
        emb = get_model().encode(got["documents"][0]).tolist()
        want = k
        n = max(1, min(k + 1, self.collection.count()))  # fetch one extra to drop self
        res = self.collection.query(query_embeddings=[emb], n_results=n)
        hits = _hits_with_scores(res)
        return [h for h in hits if h["sku"] != sku][:want]  # never more than k


# ── Helpers ──────────────────────────────────────────────────────────────────
def _parse_json_dict(meta: dict, key: str) -> dict:
    """A dict stored as a JSON string in ChromaDB metadata — parse it back."""
    raw = meta.get(key, "{}")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (json.JSONDecodeError, TypeError):
        return {}


# The fields that make up the formal PIM product model. Anything else stored on
# the Chroma record is "extra" metadata — off-model today, but potentially useful
# to enrich the product in the future, so we surface it instead of dropping it.
# `long_description` is excluded too: it's the embedded text, already shown as the
# Description blurb (the `document`), so it isn't enrichment metadata.
_KNOWN_META = {"name", "brand", "category", "price", "short_description",
               "long_description", "attributes", "extra"}


def _to_product(sku: str, meta: dict) -> dict:
    meta = dict(meta)
    # The copilot's create_product stores supplier catch-all fields under an
    # `extra` JSON string; unpack it. Also fold in any other off-model metadata
    # keys (future enrichment fields that aren't part of the PIM model).
    extra = _parse_json_dict(meta, "extra")
    for k, v in meta.items():
        if k not in _KNOWN_META:
            extra[k] = v
    return {
        "sku": sku,
        "name": meta.get("name"),
        "brand": meta.get("brand"),
        "category": meta.get("category"),
        "price": meta.get("price"),
        "short_description": meta.get("short_description"),
        "attributes": _parse_json_dict(meta, "attributes"),
        "extra": extra,
    }


def _hits_with_scores(res: dict) -> list[dict]:
    """Turn a Chroma query result into product hits with a 0–1 similarity score."""
    hits = []
    ids = res["ids"][0]
    metas = res["metadatas"][0]
    dists = res.get("distances", [[None] * len(ids)])[0]
    for sku, meta, dist in zip(ids, metas, dists):
        p = _to_product(sku, meta)
        # Chroma default metric is squared-L2 on normalised MiniLM vectors;
        # map distance → a friendly 0–1 "similarity" for display only.
        p["score"] = None if dist is None else round(1.0 / (1.0 + dist), 3)
        hits.append(p)
    return hits


# ── Taxonomy (category → expected attribute schema, for data-quality) ────────
def load_taxonomy() -> dict | None:
    f = DATA / "taxonomy.json"
    if not f.exists():
        return None
    with open(f) as fh:
        return json.load(fh)


def expected_schema(catalog: "Catalog") -> dict[str, dict]:
    """Map each category → {attribute: type/values label}.

    Primary source is the taxonomy file (the real PIM schema). If it is missing,
    fall back to the union of attribute keys actually seen per category.
    """
    tax = load_taxonomy()
    if tax:
        schema: dict[str, dict] = {}
        for top in tax["categories"]:
            for sub in top["subcategories"]:
                attrs = {}
                for a in sub["category_attributes"]:
                    if a.get("values"):
                        attrs[a["name"]] = "enum: " + ", ".join(a["values"])
                    else:
                        label = a["type"] + (f" ({a['unit']})" if a.get("unit") else "")
                        attrs[a["name"]] = label
                schema[sub["name"]] = attrs
        return schema

    # fallback: data-driven union of seen keys
    schema = {}
    for p in catalog.all_products():
        keys = schema.setdefault(p["category"], {})
        for k in p["attributes"]:
            keys.setdefault(k, "")
    return schema


# ── Index discovery (prefill the UI dropdown) ────────────────────────────────
def discover_indexes() -> list[dict]:
    """Find candidate `chroma_index` folders in the repo (those with a chroma.sqlite3)."""
    found: list[dict] = []
    seen: set[str] = set()
    roots = [PIM_PROD, REPO_ROOT]
    for root in roots:
        try:
            matches = root.rglob("chroma.sqlite3")
        except OSError:
            continue
        for sqlite in matches:
            folder = sqlite.parent.resolve()
            key = str(folder)
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "path": key,
                "label": str(folder.relative_to(REPO_ROOT))
                if REPO_ROOT in folder.parents or folder == REPO_ROOT
                else key,
            })
    found.sort(key=lambda d: d["label"])
    return found
