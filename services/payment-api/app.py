"""
payment-api — STUB (owner: Gabriel)
Objectif J1 : démarre, expose /health et /metrics, /transaction renvoie 200.
À faire : connexion PostgreSQL, vérif JWT via auth, persistance des transactions.
Le contrat d'interface (endpoints + métriques) est FIGÉ : ne pas le changer sans
prévenir l'équipe (la remédiation et le ML en dépendent).
"""
import time
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="payment-api")

# --- Métriques FIGÉES (consommées par Prometheus -> alertes -> remédiation) ---
REQUESTS = Counter("http_requests_total", "Total HTTP requests",
                   ["method", "endpoint", "status"])
LATENCY = Histogram("request_latency_seconds", "Request latency", ["endpoint"])


@app.middleware("http")
async def instrument(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    endpoint = request.url.path
    LATENCY.labels(endpoint).observe(elapsed)
    REQUESTS.labels(request.method, endpoint, response.status_code).inc()
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class Transaction(BaseModel):
    account_id: str
    amount: float
    currency: str = "EUR"


@app.post("/transaction")
def create_transaction(tx: Transaction):
    # STUB : renvoie un reçu fictif. À remplacer par persistance DB.
    return {"status": "ok", "tx_id": "stub-0001", "account_id": tx.account_id,
            "amount": tx.amount, "currency": tx.currency}


@app.get("/balance/{account_id}")
def balance(account_id: str):
    return {"account_id": account_id, "balance": 1000.0, "currency": "EUR"}
