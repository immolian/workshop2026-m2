"""
ml-detector — Détection ML branchée (IsolationForest + calibration).
Expose une gauge `anomaly_score` (0..1) scrapée par Prometheus.
La règle AnomalyDetected (rules.yml) déclenche quand anomaly_score > 0.8.
"""
import asyncio
import json
import logging

import joblib
import numpy as np
from fastapi import FastAPI, Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

from features import fetch_features, FEATURES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml-detector")

app = FastAPI(title="ml-detector")
ANOMALY = Gauge("anomaly_score", "ML anomaly score [0..1]")
ANOMALY.set(0.0)

model = joblib.load("model.joblib")
calibration = json.load(open("calibration.json"))


def to_score(d: float) -> float:
    return float(1 / (1 + np.exp(calibration["k"] * (d - calibration["center"]))))


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
            try:
                x = fetch_features()
                d = model.decision_function([x])[0]
                score = to_score(d)
                ANOMALY.set(score)
                logger.info("features=%s score=%.3f", dict(zip(FEATURES, x)), score)
            except Exception as e:
                logger.warning("erreur scoring: %s", e)
            await asyncio.sleep(5)
    asyncio.create_task(loop())