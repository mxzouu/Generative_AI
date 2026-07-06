
import json
import logging
from pathlib import Path

import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer
from mcp.server.fastmcp import FastMCP

logging.getLogger("mcp").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Paths — this file lives at notebooks/TD4_mcp/mini_project/pim_server.py,
# the shared catalog data lives at notebooks/data/.
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent.parent / "data"
PRODUCTS_CSV = DATA_DIR / "products.csv"
TAXONOMY_JSON = DATA_DIR / "taxonomy.json"

# Persistent ChromaDB store lives next to this server, not in-memory like the notebook.
CHROMA_PATH = HERE / "chroma_store"
COLLECTION_NAME = "catalog"

# Same embedding model as TD1 -> TD3 -> TD4, so the vector space matches.
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Load taxonomy once (small, static, no need for a DB).
# ---------------------------------------------------------------------------
with open(TAXONOMY_JSON, encoding="utf-8") as f:
    taxonomy = json.load(f)

# ---------------------------------------------------------------------------
# Build / open the persistent ChromaDB index. If the collection is empty,
# seed it from products.csv exactly like the notebook's §1 does — but with a
# PersistentClient so it survives across server restarts.
# ---------------------------------------------------------------------------
embed_model = SentenceTransformer(EMBED_MODEL_NAME)
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

if collection.count() == 0:
    df = pd.read_csv(PRODUCTS_CSV)
    df["doc"] = df["name"] + " — " + df["long_description"]
    embeddings = embed_model.encode(df["doc"].tolist(), show_progress_bar=False)
    collection.add(
        ids=df["sku"].tolist(),
        embeddings=embeddings.tolist(),
        documents=df["doc"].tolist(),
        metadatas=[
            {
                "name": r["name"],
                "brand": r["brand"],
                "category": r["category"],
                "price": float(r["price"]),
                "short_description": r["short_description"],
                "long_description": r["long_description"],
                "attributes": r["attributes"],  # JSON string -> Chroma metadata must be scalar
            }
            for _, r in df.iterrows()
        ],
    )

# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------
mcp_server = FastMCP("pim")


def _hit_from_meta(sku: str, meta: dict) -> dict:
    """Turn a raw Chroma id + metadata dict into the product dict we hand back."""
    hit = {"sku": sku, **meta}
    if isinstance(hit.get("attributes"), str):
        try:
            hit["attributes"] = json.loads(hit["attributes"])
        except json.JSONDecodeError:
            pass
    return hit


@mcp_server.tool()
def search_products(query: str, k: int = 3) -> list:
    """Semantic search over the product catalog; returns up to k products most similar to the query."""
    q_vec = embed_model.encode(query).tolist()
    res = collection.query(query_embeddings=[q_vec], n_results=k)
    hits = []
    for sku, meta in zip(res["ids"][0], res["metadatas"][0]):
        hits.append(_hit_from_meta(sku, meta))
    return hits


@mcp_server.tool()
def get_product(sku: str) -> dict:
    """Return one product's full stored data (document + metadata) by its SKU, or {} if not found."""
    res = collection.get(ids=[sku])
    if not res["ids"]:
        return {}
    hit = _hit_from_meta(res["ids"][0], res["metadatas"][0])
    hit["doc"] = res["documents"][0]
    return hit


@mcp_server.tool()
def get_category_tree() -> dict:
    """Return the catalog's category tree as {top_category: [leaf_category, ...]}."""
    return {
        cat["name"]: [sub["name"] for sub in cat["subcategories"]]
        for cat in taxonomy["categories"]
    }


@mcp_server.tool()
def get_category_attributes(category: str) -> dict:
    """Return the applicable attribute schema for a leaf category, as {attribute_name: type_or_values}."""
    for cat in taxonomy["categories"]:
        for sub in cat["subcategories"]:
            if sub["name"] != category:
                continue
            attrs = {}
            for attr in sub.get("category_attributes", []):
                if "values" in attr:
                    attrs[attr["name"]] = f"{attr['type']} ({', '.join(attr['values'])})"
                elif "unit" in attr:
                    attrs[attr["name"]] = f"{attr['type']} ({attr['unit']})"
                else:
                    attrs[attr["name"]] = attr["type"]
            return attrs
    return {}


@mcp_server.tool()
def create_product(
    sku: str,
    name: str,
    brand: str,
    category: str,
    price: float,
    short_description: str,
    long_description: str,
    attributes: dict,
) -> dict:
    """Create a new product: embed it and add it to the persistent catalog index (immediately searchable)."""
    doc = f"{name} — {long_description}"
    embedding = embed_model.encode(doc).tolist()
    collection.add(
        ids=[sku],
        embeddings=[embedding],
        documents=[doc],
        metadatas=[
            {
                "name": name,
                "brand": brand,
                "category": category,
                "price": float(price),
                "short_description": short_description,
                "long_description": long_description,
                "attributes": json.dumps(attributes),
            }
        ],
    )
    return {"status": "created", "sku": sku}


@mcp_server.tool()
def delete_product(sku: str) -> dict:
    """Delete a product from the catalog index by its SKU."""
    existing = collection.get(ids=[sku])
    if not existing["ids"]:
        return {"status": "not_found", "sku": sku}
    collection.delete(ids=[sku])
    return {"status": "deleted", "sku": sku}


if __name__ == "__main__":
    # stdio transport: an MCP client (Claude Desktop, client_demo.py, TD5 agent)
    # spawns this process and talks to it over stdin/stdout.
    mcp_server.run()
