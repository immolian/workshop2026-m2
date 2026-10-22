"""
ask.py — Pose une question au RAG : récupère les passages pertinents dans
Chroma, puis les donne au modèle pour qu'il réponde à partir d'eux.
Usage : python ask.py "ta question"
"""
import sys

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_chroma import Chroma

PERSIST_DIR = "chroma_db"

embeddings = OllamaEmbeddings(model="nomic-embed-text")
db = Chroma(persist_directory=PERSIST_DIR, embedding_function=embeddings)
llm = ChatOllama(model="llama3.1:8b", temperature=0)


def ask(question: str) -> str:
    results = db.similarity_search(question, k=4)
    context = "\n\n---\n\n".join(doc.page_content for doc in results)
    prompt = (
        "Tu es un assistant de CONSULTATION en lecture seule pour l'équipe "
        "du projet RESILIENCE-ALPHA. Réponds UNIQUEMENT à partir du contexte "
        "fourni ci-dessous. Si l'information n'y figure pas, dis-le clairement "
        "plutôt que d'inventer une réponse.\n\n"
        f"Contexte :\n{context}\n\n"
        f"Question : {question}\n\n"
        "Réponse :"
    )
    return llm.invoke(prompt).content


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Quel est le rôle du WAF dans ce projet ?"
    print(f"Question : {question}\n")
    print(ask(question))