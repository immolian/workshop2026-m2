"""
remediation-engine — STUB (owner: Tom)
Reçoit les alertes Alertmanager sur /webhook, décide une action, l'exécute via
le docker-socket-proxy (JAMAIS le socket brut).

J1 : DRY_RUN=true -> log la décision SANS agir. C'est l'état attendu lundi.
Mercredi : DRY_RUN=false -> exécute réellement le restart et boucle la reprise.

Contrat d'alerte (annotations Prometheus) :
  action = restart | scale | block
  target = <nom_de_conteneur>
"""
import os
import logging
from fastapi import FastAPI, Request
import docker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [remediation] %(message)s")
log = logging.getLogger("remediation")

app = FastAPI(title="remediation-engine")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
# DOCKER_HOST=tcp://docker-socket-proxy:2375 -> accès restreint (pas d'exec)
client = docker.from_env()


@app.get("/health")
def health():
    return {"status": "ok", "dry_run": DRY_RUN}


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    actions = []
    for alert in payload.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        ann = alert.get("annotations", {})
        action = ann.get("action", "restart")
        target = ann.get("target")
        if not target:
            continue
        actions.append({"action": action, "target": target})
        log.info("Alerte reçue -> action=%s target=%s (dry_run=%s)",
                 action, target, DRY_RUN)
        if not DRY_RUN:
            _execute(action, target)
    return {"handled": actions}


def _execute(action: str, target: str):
    try:
        if action == "restart":
            container = client.containers.get(target)
            container.restart(timeout=5)
            log.info("RESTART exécuté sur %s", target)
        else:
            log.warning("Action non implémentée : %s", action)
    except Exception as e:  # noqa: BLE001
        log.error("Échec remédiation %s sur %s : %s", action, target, e)
