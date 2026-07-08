"""Construit l'index ChromaDB de la doc interne (RAG avec citation page).

Chunking PAGE PAR PAGE : chaque page d'un PDF devient un (ou plusieurs) chunk(s) portant
la métadonnée {source, page}. C'est ce qui permet à search_internal_docs de répondre en
citant (fichier.pdf, p.N). Embeddings locaux SentenceTransformers all-MiniLM-L6-v2 (même
espace vectoriel que les TD, aucun appel API -> quota Haiku préservé).

Prérequis : scripts/generate_pdfs.py déjà exécuté.
Usage :  python scripts/build_chroma_index.py
"""
from __future__ import annotations

from pathlib import Path

import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DOCS_DIR = PROJECT / "data" / "docs"
CHROMA_PATH = PROJECT / "chroma_index"
COLLECTION = "internal_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"
MAX_CHARS = 1200  # au-delà, on découpe la page en sous-chunks


def _split(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text] if text else []
    chunks, cur = [], ""
    for sentence in text.replace(". ", ".\n").split("\n"):
        if len(cur) + len(sentence) > max_chars and cur:
            chunks.append(cur.strip())
            cur = ""
        cur += sentence + " "
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def build() -> None:
    pdfs = sorted(DOCS_DIR.glob("*.pdf"))
    if not pdfs:
        raise SystemExit("Aucun PDF dans data/docs/ — lance d'abord generate_pdfs.py")

    embedder = SentenceTransformer(EMBED_MODEL)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    col = client.create_collection(COLLECTION)

    ids, docs, metas = [], [], []
    for pdf in pdfs:
        reader = PdfReader(str(pdf))
        for page_no, page in enumerate(reader.pages, start=1):
            for k, chunk in enumerate(_split(page.extract_text() or "")):
                ids.append(f"{pdf.stem}_p{page_no}_{k}")
                docs.append(chunk)
                metas.append({"source": pdf.name, "page": page_no})

    embeddings = embedder.encode(docs, show_progress_bar=False, batch_size=64)
    col.add(ids=ids, documents=docs, embeddings=[e.tolist() for e in embeddings], metadatas=metas)

    print(f"[OK] Index ChromaDB construit : {CHROMA_PATH}")
    print(f"   {len(pdfs)} PDF -> {len(ids)} chunks indexes (collection '{COLLECTION}')")


if __name__ == "__main__":
    build()
