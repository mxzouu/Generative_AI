"""Light PIM — FastAPI backend.

Serves a small JSON API over a ChromaDB product catalog plus the static Vue UI.
One process: `uvicorn app.main:app` exposes both the `/api/*` routes and the
single-page app at `/`.

The active index is switchable at runtime (`POST /api/index`), so the viewer can
read whichever `chroma_index` folder you point it at — including the one a
student's TD5 copilot writes to.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .catalog import (DEFAULT_INDEX, Catalog, IndexError_, discover_indexes,
                      expected_schema)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
START_INDEX = os.environ.get("PIM_INDEX_DIR", str(DEFAULT_INDEX))

app = FastAPI(title="Light PIM", version="1.0")

# Single shared catalog instance; `POST /api/index` swaps the folder it reads.
# Catalog boots unbound (no crash) if the start index is missing/empty.
catalog = Catalog(START_INDEX)


@app.exception_handler(IndexError_)
def _no_index_handler(request: Request, exc: IndexError_):
    """No index loaded yet → a friendly 503 the UI can show, not a 500/crash."""
    return JSONResponse(status_code=503, content={"error": str(exc)})


# ── Request models ───────────────────────────────────────────────────────────
class SearchBody(BaseModel):
    query: str
    k: int = 12


class IndexBody(BaseModel):
    path: str


# ── Products ─────────────────────────────────────────────────────────────────
@app.get("/api/products")
def list_products():
    return {"products": catalog.all_products(), "total": catalog.collection.count()}


@app.get("/api/products/{sku}")
def get_product(sku: str):
    product = catalog.get_product(sku)
    if product is None:
        raise HTTPException(404, f"No product with SKU {sku!r}")
    # attach the category's expected attributes + which ones are missing
    schema = expected_schema(catalog).get(product["category"], {})
    present = set(product["attributes"].keys())
    product["expected_attributes"] = schema
    product["missing_attributes"] = [k for k in schema if k not in present]
    return product


@app.delete("/api/products/{sku}")
def delete_product(sku: str):
    if not catalog.delete(sku):
        raise HTTPException(404, f"No product with SKU {sku!r}")
    return {"status": "deleted", "sku": sku, "total": catalog.collection.count()}


@app.get("/api/products/{sku}/similar")
def similar_products(sku: str, k: int = 5):
    return {"similar": catalog.similar(sku, k=k)}


# ── Semantic search ──────────────────────────────────────────────────────────
@app.post("/api/search")
def search(body: SearchBody):
    if not body.query.strip():
        return {"results": []}
    return {"results": catalog.search(body.query, k=body.k)}


# ── Categories / stats / quality ─────────────────────────────────────────────
@app.get("/api/categories")
def categories():
    return {"schema": expected_schema(catalog)}


@app.get("/api/stats")
def stats():
    products = catalog.all_products()
    by_category = Counter(p["category"] for p in products)
    by_brand = Counter(p["brand"] for p in products if p["brand"])
    prices = [p["price"] for p in products if isinstance(p["price"], (int, float))]
    price_stats = None
    histogram = []
    if prices:
        lo, hi = min(prices), max(prices)
        price_stats = {"min": lo, "max": hi, "avg": round(sum(prices) / len(prices), 2)}
        # 8 even buckets across the price range
        n_buckets = 8
        span = (hi - lo) or 1.0
        width = span / n_buckets
        counts = [0] * n_buckets
        for v in prices:
            idx = min(int((v - lo) / width), n_buckets - 1)
            counts[idx] += 1
        histogram = [
            {
                "from": round(lo + i * width, 2),
                "to": round(lo + (i + 1) * width, 2),
                "count": c,
            }
            for i, c in enumerate(counts)
        ]
    return {
        "total": len(products),
        "categories": len(by_category),
        "brands": len(by_brand),
        "by_category": [{"name": n, "count": c} for n, c in by_category.most_common()],
        "top_brands": [{"name": n, "count": c} for n, c in by_brand.most_common(12)],
        "price": price_stats,
        "histogram": histogram,
    }


@app.get("/api/quality")
def quality():
    schema = expected_schema(catalog)
    products = catalog.all_products()
    rows: dict[str, dict] = {}
    issues = []
    for p in products:
        expected = schema.get(p["category"], {})
        present = set(p["attributes"].keys())
        missing = [k for k in expected if k not in present]
        row = rows.setdefault(
            p["category"],
            {"category": p["category"], "products": 0, "complete": 0, "expected": len(expected)},
        )
        row["products"] += 1
        if not missing:
            row["complete"] += 1
        else:
            issues.append({
                "sku": p["sku"],
                "name": p["name"],
                "category": p["category"],
                "missing": missing,
            })
    summary = []
    for r in rows.values():
        r["completeness"] = round(100 * r["complete"] / r["products"]) if r["products"] else 100
        summary.append(r)
    summary.sort(key=lambda r: (r["completeness"], r["category"]))
    return {"summary": summary, "issues": issues}


# ── Index selection ──────────────────────────────────────────────────────────
@app.get("/api/index")
def get_index():
    return catalog.info()


@app.post("/api/index")
def set_index(body: IndexBody):
    try:
        catalog.switch(body.path)
    except IndexError_ as e:
        raise HTTPException(400, str(e))
    return catalog.info()


@app.get("/api/index/discover")
def discover():
    return {"indexes": discover_indexes(),
            "current": str(catalog.path) if catalog.path else None}


# ── Static frontend (mounted last so /api/* wins) ────────────────────────────
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
