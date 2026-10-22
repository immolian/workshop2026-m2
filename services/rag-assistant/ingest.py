"""
ingest.py — Charge les documents du dossier docs/, les découpe, et construit
la base vectorielle Chroma utilisée par le RAG.
Usage : python ingest.py
"""
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

DOCS_DIR = "docs"
PERSIST_DIR = "chroma_db"

print(f"Chargement des documents depuis {DOCS_DIR}/ ...")
loader = DirectoryLoader(DOCS_DIR, glob="**/*.md", loader_cls=TextLoader,
                          loader_kwargs={"encoding": "utf-8"})
docs = loader.load()
print(f"{len(docs)} document(s) chargé(s).")

splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
chunks = splitter.split_documents(docs)
print(f"{len(chunks)} morceaux (chunks) créés.")

print("Calcul des embeddings et écriture dans Chroma (peut prendre un moment)...")
embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma.from_documents(chunks, embeddings, persist_directory=PERSIST_DIR)

print(f"Terminé. Base vectorielle sauvegardée dans {PERSIST_DIR}/")