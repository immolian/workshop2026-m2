"""
rag-assistant — Assistant de consultation en lecture seule (RAG).
Répond aux questions sur la documentation de l'équipe (procédures, architecture).
AUCUN accès privilégié au système : pas d'outil, pas de shell, pas d'API vers
remediation-engine. Uniquement de la recherche documentaire + génération de texte.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma

PERSIST_DIR = "chroma_db"

app = FastAPI(title="rag-assistant")

embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma(persist_directory=PERSIST_DIR, embedding_function=embeddings)
llm = ChatOllama(model="llama3.1:8b", temperature=0)


class Question(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(q: Question):
    results = db.similarity_search(q.question, k=4)
    context = "\n\n---\n\n".join(doc.page_content for doc in results)
    prompt = (
        "Tu es un assistant de CONSULTATION en lecture seule pour l'équipe "
        "du projet RESILIENCE-ALPHA. Réponds UNIQUEMENT à partir du contexte "
        "fourni ci-dessous. Si l'information n'y figure pas, dis-le clairement "
        "plutôt que d'inventer une réponse. Tu n'as aucune capacité d'action "
        "sur le système : si on te le demande, rappelle que tu es un assistant "
        "de lecture seule.\n\n"
        f"Contexte :\n{context}\n\n"
        f"Question : {q.question}\n\n"
        "Réponse :"
    )
    answer = llm.invoke(prompt).content
    sources = list({doc.metadata.get("source", "inconnu") for doc in results})
    return {"answer": answer, "sources": sources}