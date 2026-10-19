"""
ml-detector — STUB (owner: Mahalia)
Expose une gauge `anomaly_score` (0..1) scrapée par Prometheus.
La règle AnomalyDetected (rules.yml) déclenche quand anomaly_score > 0.8.

À faire :
  1. Interroger Prometheus (PROMETHEUS_URL) pour récupérer rate/latence/5xx.
  2. Entraîner un modèle (IsolationForest) sur du trafic normal (baseline).
  3. Publier le score d'anomalie en continu dans la gauge ci-dessous.
Le modèle doit alimenter la remédiation : c'est l'exigence "ML branché" (Axe 2).
"""
import asyncio
from fastapi import FastAPI, Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="ml-detector")
ANOMALY = Gauge("anomaly_score", "ML anomaly score [0..1]")
ANOMALY.set(0.0)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.on_event("startup")
async def scoring_loop():
    async def loop():
        while True:
            # STUB : score statique. Remplacer par l'inférence du modèle.
            ANOMALY.set(0.0)
            await asyncio.sleep(5)
    asyncio.create_task(loop())
