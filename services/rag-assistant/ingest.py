"""
ingest.py — Charge les documents de référence du projet (README racine +
dossier docs/), les découpe, et construit la base vectorielle Chroma.
Usage : python ingest.py
"""
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

# Racine du repo = deux niveaux au-dessus de services/rag-assistant/
REPO_ROOT = Path(__file__).resolve().parents[2]
PERSIST_DIR = "chroma_db"

SOURCE_FILES = [REPO_ROOT / "README.md"]
docs_dir = REPO_ROOT / "docs"
if docs_dir.is_dir():
    SOURCE_FILES += sorted(docs_dir.glob("*.md"))

print(f"Sources repérées : {[str(p.relative_to(REPO_ROOT)) for p in SOURCE_FILES]}")

docs = []
for path in SOURCE_FILES:
    docs.extend(TextLoader(str(path), encoding="utf-8").load())
print(f"{len(docs)} document(s) chargé(s).")

splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
chunks = splitter.split_documents(docs)
print(f"{len(chunks)} morceaux (chunks) créés.")

print("Calcul des embeddings et écriture dans Chroma (peut prendre un moment)...")
embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma.from_documents(chunks, embeddings, persist_directory=PERSIST_DIR)

print(f"Terminé. Base vectorielle sauvegardée dans {PERSIST_DIR}/")