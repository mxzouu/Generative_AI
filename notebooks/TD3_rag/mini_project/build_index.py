"""Build a persistent ChromaDB index of the product catalog. Run once (or after products.csv changes):

    python build_index.py
"""
from pathlib import Path

import chromadb
import pandas as pd
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "../../data/products.csv"
INDEX_PATH = HERE / "chroma_db"


def main():
    df = pd.read_csv(DATA_PATH)
    df["doc"] = df["name"] + " — " + df["long_description"]

    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = embed_model.encode(df["doc"].tolist()).tolist()

    client = chromadb.PersistentClient(path=str(INDEX_PATH))
    if "catalog" in [c.name for c in client.list_collections()]:
        client.delete_collection("catalog")
    collection = client.create_collection("catalog")

    metadatas = [
        {
            "name": r["name"],
            "brand": r["brand"],
            "category": r["category"],
            "price": float(r["price"]),
            "short_description": r["short_description"],
            "long_description": r["long_description"],
            "attributes": r["attributes"],
        }
        for _, r in df.iterrows()
    ]

    collection.add(
        ids=df["sku"].tolist(),
        embeddings=embeddings,
        documents=df["doc"].tolist(),
        metadatas=metadatas,
    )

    print(f"Indexed {collection.count()} products into '{INDEX_PATH}'.")


if __name__ == "__main__":
    main()
