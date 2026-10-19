"""
remediation-engine — owner: Tom
Reçoit les alertes Alertmanager sur /webhook, décide une action, l'exécute via
le docker-socket-proxy (JAMAIS le socket brut), puis PROUVE la reprise :
  1. /health de la cible répond "ok" (reprise technique)
  2. transaction canari POST /transaction réussie (reprise métier)
Un restart seul n'est PAS une preuve de reprise.

Contrat d'alerte (annotations Prometheus) — FIGÉ :
  action = restart | scale | block
  target = <nom_de_conteneur>

Modes : DRY_RUN=true (défaut) -> journalise la décision SANS agir.
        DRY_RUN=false         -> exécute le restart et vérifie la reprise.

Timeline (un log JSON par étape, corrélé par incident_id, lisible dans Loki via
`{container="remediation-engine"} | json`) :
  webhook_received -> alert_received -> decision
  -> action_started -> action_done -> verify_health_ok -> verify_canary_ok
  -> recovery_confirmed | recovery_failed

-----------------------------------------------------------------------------
SÉCURITÉ (Axe 2) — périmètre Docker et risque résiduel (repris dans l'EBIOS)
-----------------------------------------------------------------------------
Contrôles en place (docker-compose.yml, service docker-socket-proxy) :
  - EXEC=0, IMAGES=0, VOLUMES=0, NETWORKS=0, INFO=0 : pas de shell distant, pas
    de pull/build d'image, pas d'accès aux volumes ni aux réseaux.
  - Le moteur ne publie AUCUN port sur l'hôte et vit uniquement sur backend-net
    (internal:true). Il parle au proxy en TCP, jamais à /var/run/docker.sock.
  - Liste blanche ALLOWED_TARGETS : le moteur refuse d'agir sur un conteneur hors
    liste (ex. db, docker-socket-proxy), même si une alerte le demande.

Risque résiduel :
  - CONTAINERS=1 + POST=1 n'autorise pas "restart" seul : le proxy filtre par
    préfixe d'URL (/containers) et POST=1 ouvre TOUTES les méthodes d'écriture
    (POST/PUT/DELETE) sur ce préfixe — create, start/stop/kill, update, rename,
    attach, suppression. Un attaquant qui compromet le moteur (ou qui
    atteint le proxy depuis backend-net) peut créer un conteneur privilégié
    montant / de l'hôte -> élévation jusqu'à root sur la VM Docker.
  - Le montage ":ro" du socket côté proxy ne protège rien : un socket Unix en
    lecture seule accepte quand même les écritures d'API.
  - /webhook n'est pas authentifié : tout service de backend-net peut déclencher
    un restart (borné par ALLOWED_TARGETS + cooldown -> au pire un DoS par
    restarts espacés de COOLDOWN_SECONDS).
Pistes de réduction : ALLOW_RESTARTS=1 à la place de POST=1 (versions récentes
du proxy), proxy dédié sur un réseau réservé au moteur, bearer token Alertmanager
(http_config.authorization) vérifié ici, conteneurs cibles en read_only.
"""
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import docker
import requests
from fastapi import FastAPI, HTTPException, Request

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
COOLDOWN_SECONDS = float(os.getenv("COOLDOWN_SECONDS", "60"))
ALLOWED_TARGETS = {t.strip() for t in os.getenv("ALLOWED_TARGETS", "payment-api,auth").split(",") if t.strip()}
# URL interne de la cible (réseau backend-net) ; {target} = nom du conteneur.
VERIFY_URL_TEMPLATE = os.getenv("VERIFY_URL_TEMPLATE", "http://{target}:8000")
HEALTH_TIMEOUT_SECONDS = float(os.getenv("HEALTH_TIMEOUT_SECONDS", "60"))
HEALTH_POLL_INTERVAL = float(os.getenv("HEALTH_POLL_INTERVAL", "2"))
CANARY_RETRIES = int(os.getenv("CANARY_RETRIES", "3"))
RESTART_TIMEOUT = int(os.getenv("RESTART_TIMEOUT", "5"))
# Transaction fictive, identifiable dans les logs/DB de payment-api.
CANARY_PAYLOAD = {"account_id": "canary-remediation", "amount": 0.01, "currency": "EUR"}
SUPPORTED_ACTIONS = {"restart", "scale", "block"}


# --------------------------------------------------------------------------- #
# Journalisation structurée (JSON une ligne / événement -> Promtail -> Loki)
# --------------------------------------------------------------------------- #
class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": "remediation-engine",
            "event": record.getMessage(),
            "dry_run": DRY_RUN,
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
log = logging.getLogger("remediation")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.propagate = False


def emit(event: str, level: int = logging.INFO, **fields):
    log.log(level, event, extra={"fields": fields})


# --------------------------------------------------------------------------- #
# État en mémoire (anti-boucle)
# --------------------------------------------------------------------------- #
_state_lock = threading.Lock()
_last_action: dict[str, float] = {}   # target -> monotonic() de la dernière décision d'agir
_in_flight: set[str] = set()          # cibles en cours de remédiation/vérification

_docker_client = None


def docker_client():
    """Client paresseux : DOCKER_HOST=tcp://docker-socket-proxy:2375 (jamais le socket brut)."""
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


app = FastAPI(title="remediation-engine")


@app.get("/health")
def health():
    return {"status": "ok", "dry_run": DRY_RUN}


# --------------------------------------------------------------------------- #
# Webhook Alertmanager
# --------------------------------------------------------------------------- #
@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        emit("webhook_rejected", logging.WARNING, reason="invalid_json")
        raise HTTPException(status_code=400, detail="invalid JSON")
    alerts = payload.get("alerts") if isinstance(payload, dict) else None
    if not isinstance(alerts, list):
        emit("webhook_rejected", logging.WARNING, reason="missing_alerts_list")
        raise HTTPException(status_code=400, detail="expected {alerts:[...]}")

    emit("webhook_received", alerts=len(alerts), group_key=payload.get("groupKey"))
    decisions = handle_alerts(alerts)
    return {"handled": decisions}


def parse_alerts(alerts: list) -> tuple[list[dict], list[dict]]:
    """Ne garde que les alertes firing valides, dédupliquées par cible.
    Retourne (à traiter, ignorées)."""
    selected: dict[str, dict] = {}
    ignored: list[dict] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            ignored.append({"reason": "malformed_alert"})
            continue
        labels = alert.get("labels") or {}
        ann = alert.get("annotations") or {}
        name = labels.get("alertname", "unknown")
        status = alert.get("status")
        action = (ann.get("action") or "restart").strip().lower()
        target = (ann.get("target") or "").strip()
        info = {"alertname": name, "action": action, "target": target or None}
        emit("alert_received", status=status, severity=labels.get("severity"), **info)

        if status != "firing":
            ignored.append({**info, "reason": f"status_{status}"})
        elif not target:
            ignored.append({**info, "reason": "missing_target"})
        elif target in selected:
            selected[target]["alertnames"].append(name)
            ignored.append({**info, "reason": "duplicate_in_batch"})
        else:
            selected[target] = {"action": action, "target": target, "alertnames": [name]}
    return list(selected.values()), ignored


def handle_alerts(alerts: list) -> list[dict]:
    to_handle, ignored = parse_alerts(alerts)
    decisions = []
    for item in ignored:
        emit("decision", decision="ignore", **item)
        decisions.append({**item, "decision": "ignore"})

    for item in to_handle:
        target, action = item["target"], item["action"]
        reason = None
        if action not in SUPPORTED_ACTIONS:
            reason = "unknown_action"
        elif target not in ALLOWED_TARGETS:
            reason = "target_not_allowed"
        else:
            with _state_lock:
                now = time.monotonic()
                last = _last_action.get(target)
                if target in _in_flight:
                    reason = "remediation_in_progress"
                elif last is not None and now - last < COOLDOWN_SECONDS:
                    reason = "cooldown"
                    item["cooldown_remaining_s"] = round(COOLDOWN_SECONDS - (now - last), 1)
                else:
                    # Réservation atomique : une salve concurrente ne passe qu'une fois.
                    _last_action[target] = now
                    _in_flight.add(target)

        if reason:
            level = logging.WARNING if reason in ("unknown_action", "target_not_allowed") else logging.INFO
            emit("decision", level, decision="ignore", reason=reason, **item)
            decisions.append({**item, "decision": "ignore", "reason": reason})
            continue

        incident_id = uuid.uuid4().hex[:8]
        decision = "log_only" if DRY_RUN else "execute"
        emit("decision", decision=decision, incident_id=incident_id,
             cooldown_s=COOLDOWN_SECONDS, **item)
        decisions.append({**item, "decision": decision, "incident_id": incident_id})
        # Réponse immédiate à Alertmanager ; restart + vérification en arrière-plan.
        threading.Thread(target=remediate, args=(incident_id, action, target),
                         name=f"remediate-{target}", daemon=True).start()
    return decisions


# --------------------------------------------------------------------------- #
# Remédiation + preuve de reprise
# --------------------------------------------------------------------------- #
def remediate(incident_id: str, action: str, target: str):
    started = time.monotonic()
    ctx = {"incident_id": incident_id, "action": action, "target": target}
    try:
        if DRY_RUN:
            emit("action_skipped_dry_run", **ctx)
            return
        if action == "restart":
            if not do_restart(ctx):
                emit("recovery_failed", logging.ERROR, reason="action_failed",
                     duration_s=round(time.monotonic() - started, 2), **ctx)
                return
        else:
            # TODO(scale) : docker-compose --scale / service update — hors périmètre 4 jours.
            # TODO(block) : règle WAF / iptables sur l'IP source — hors périmètre 4 jours.
            emit("action_not_implemented", logging.WARNING, **ctx)
            return

        ok, reason = verify_recovery(ctx)
        duration = round(time.monotonic() - started, 2)
        if ok:
            emit("recovery_confirmed", time_to_recover_s=duration, **ctx)
        else:
            emit("recovery_failed", logging.ERROR, reason=reason, duration_s=duration, **ctx)
    except Exception as e:  # noqa: BLE001 — un thread de remédiation ne doit jamais mourir en silence
        emit("recovery_failed", logging.ERROR, reason="unexpected_error", error=str(e), **ctx)
    finally:
        with _state_lock:
            _in_flight.discard(target)
            if not DRY_RUN:
                # Le cooldown court à partir de la FIN de la remédiation : les alertes
                # encore "firing" pendant la reprise ne relancent pas un restart.
                _last_action[target] = time.monotonic()


def do_restart(ctx: dict) -> bool:
    target = ctx["target"]
    emit("action_started", restart_timeout_s=RESTART_TIMEOUT, **ctx)
    try:
        container = docker_client().containers.get(target)
        container.restart(timeout=RESTART_TIMEOUT)
        container.reload()
        emit("action_done", container_status=container.status, **ctx)
        return True
    except Exception as e:  # noqa: BLE001
        emit("action_failed", logging.ERROR, error=str(e), **ctx)
        return False


def verify_recovery(ctx: dict) -> tuple[bool, str]:
    base = VERIFY_URL_TEMPLATE.format(target=ctx["target"])

    # 1) Reprise technique : /health == ok
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            r = requests.get(f"{base}/health", timeout=3)
            if r.status_code == 200 and r.json().get("status") == "ok":
                emit("verify_health_ok", attempt=attempt, **ctx)
                break
            last_err = f"http_{r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_err = type(e).__name__
        if time.monotonic() >= deadline:
            emit("verify_health_timeout", logging.ERROR, attempts=attempt,
                 last_error=last_err, timeout_s=HEALTH_TIMEOUT_SECONDS, **ctx)
            return False, "health_timeout"
        emit("verify_health_pending", attempt=attempt, last_error=last_err, **ctx)
        time.sleep(HEALTH_POLL_INTERVAL)

    # 2) Reprise métier : transaction canari
    for attempt in range(1, CANARY_RETRIES + 1):
        try:
            t0 = time.monotonic()
            r = requests.post(f"{base}/transaction", json=CANARY_PAYLOAD, timeout=5)
            latency_ms = round((time.monotonic() - t0) * 1000)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and body.get("status") == "ok":
                emit("verify_canary_ok", attempt=attempt, tx_id=body.get("tx_id"),
                     latency_ms=latency_ms, **ctx)
                return True, "ok"
            err = f"http_{r.status_code}"
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        emit("verify_canary_failed", logging.WARNING, attempt=attempt, error=err, **ctx)
        time.sleep(HEALTH_POLL_INTERVAL)
    return False, "canary_failed"
