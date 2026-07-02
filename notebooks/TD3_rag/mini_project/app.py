"""Fnac-style catalog chatbot — a thin Flask wrapper around the retrieve -> answer loop from TD3 §7.

Run:
    python build_index.py   # once, builds the persistent index
    python app.py            # then start the web app on http://127.0.0.1:5000
"""
import os
from pathlib import Path

import chromadb
from anthropic import Anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from sentence_transformers import SentenceTransformer

load_dotenv()  # walks up to the project-root .env, same as the notebook
if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY not found. Add it to the .env file at the project root."
    )

HERE = Path(__file__).resolve().parent
INDEX_PATH = HERE / "chroma_db"
MODEL = "claude-haiku-4-5"

if not INDEX_PATH.exists():
    raise RuntimeError(
        f"No index found at '{INDEX_PATH}'. Run `python build_index.py` first."
    )

client = Anthropic()
embed_model = SentenceTransformer("all-MiniLM-L6-v2")
chroma_client = chromadb.PersistentClient(path=str(INDEX_PATH))
collection = chroma_client.get_collection("catalog")

app = Flask(__name__)


def retrieve(query_text, k=4):
    """Same retriever as TD3 §2, backed by the persistent index instead of the in-memory one."""
    query_embedding = embed_model.encode(query_text).tolist()
    results = collection.query(query_embeddings=[query_embedding], n_results=k)
    hits = []
    for i in range(len(results["ids"][0])):
        hit = {"sku": results["ids"][0][i]}
        hit.update(results["metadatas"][0][i])
        hits.append(hit)
    return hits


def answer_question(question, k=4):
    """Same retrieve -> grounded-answer loop as TD3 §7."""
    hits = retrieve(question, k=k)
    context = "\n".join(
        f"- {h['name']} ({h['category']}): {h['short_description']}" for h in hits
    )
    prompt = (
        "Answer the question using ONLY the catalog products listed below. If nothing fits, say so.\n\n"
        f"Catalog products:\n{context}\n\nQuestion: {question}"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text, hits


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
def ask():
    question = (request.get_json(silent=True) or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "Please type a question."}), 400
    answer, hits = answer_question(question)
    return jsonify({
        "answer": answer,
        "sources": [{"name": h["name"], "category": h["category"]} for h in hits],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
