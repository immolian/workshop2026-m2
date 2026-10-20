#!/usr/bin/env python3
"""
prom_export.py — Mesure et export des features d'observabilité depuis Prometheus.

Deux modes :
  probe  : snapshot instantané PAR CONTENEUR (job) — à regarder EN DIRECT pendant le
           flood pour voir qui sature et si le ratio 5xx dépasse 25 %.
  range  : export d'une fenêtre temporelle en CSV labellisé, pour l'entraînement ML.

Prometheus n'étant pas exposé sur l'hôte, ce script tourne SUR le réseau interne du
compose (voir le runbook d'accompagnement : `docker compose run ... payment-api ...`).

Dépendances : stdlib uniquement (urllib, json, csv). Métriques FIGÉES par le contrat.
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --- PromQL (noms de métriques FIGÉS par le contrat d'interface) -------------
WINDOW = "30s"  # fenêtre de rate, alignée sur la règle HighErrorRate

Q_RATE = f"sum(rate(http_requests_total[{WINDOW}]))"
Q_ERR_RATIO = (
    f'sum(rate(http_requests_total{{status=~"5.."}}[{WINDOW}]))'
    f" / sum(rate(http_requests_total[{WINDOW}]))"
)
Q_P95 = (
    f"histogram_quantile(0.95, "
    f"sum(rate(request_latency_seconds_bucket[{WINDOW}])) by (le))"
)

# Déclinaisons PAR CONTENEUR (job) — pour répondre : QUI émet les 5xx ?
Q_ERR_BY_JOB = (
    f'sum by (job)(rate(http_requests_total{{status=~"5.."}}[{WINDOW}]))'
    f" / sum by (job)(rate(http_requests_total[{WINDOW}]))"
)
Q_RATE_BY_JOB = f"sum by (job)(rate(http_requests_total[{WINDOW}]))"
Q_P95_BY_JOB = (
    f"histogram_quantile(0.95, "
    f"sum(rate(request_latency_seconds_bucket[{WINDOW}])) by (le, job))"
)


def _get(prom, path, params):
    url = prom.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=10) as r:
        payload = json.load(r)
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus a répondu une erreur : {payload}")
    return payload["data"]["result"]


def _num(v):
    """Valeur Prometheus -> float. NaN (dénominateur nul) ou absent -> 0.0."""
    try:
        f = float(v)
        return 0.0 if f != f else f  # f != f est vrai uniquement pour NaN
    except (TypeError, ValueError):
        return 0.0


def query_instant(prom, q):
    return _get(prom, "/api/v1/query", {"query": q})


def query_range(prom, q, start, end, step):
    return _get(
        prom, "/api/v1/query_range",
        {"query": q, "start": start, "end": end, "step": step},
    )


def probe(prom):
    """Snapshot par conteneur : req/s, p95, ratio 5xx. Flague les jobs > 25 % 5xx."""
    err = {s["metric"].get("job", "?"): _num(s["value"][1])
           for s in query_instant(prom, Q_ERR_BY_JOB)}
    rate = {s["metric"].get("job", "?"): _num(s["value"][1])
            for s in query_instant(prom, Q_RATE_BY_JOB)}
    p95 = {s["metric"].get("job", "?"): _num(s["value"][1])
           for s in query_instant(prom, Q_P95_BY_JOB)}

    jobs = sorted(set(err) | set(rate) | set(p95))
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"\n[{ts} UTC]")
    print(f"  {'job':<16}{'req/s':>9}{'p95 (s)':>10}{'5xx ratio':>12}")
    for j in jobs:
        flag = "   <== 5xx > 25 %" if err.get(j, 0.0) > 0.25 else ""
        print(f"  {j:<16}{rate.get(j, 0.0):>9.1f}"
              f"{p95.get(j, 0.0):>10.3f}{err.get(j, 0.0):>11.1%}{flag}")


def export_range(prom, start, end, step, label, out):
    """Export CSV agrégé (colonnes attendues par Mahalia) sur une fenêtre."""
    series = {
        "req_rate": query_range(prom, Q_RATE, start, end, step),
        "p95_latency": query_range(prom, Q_P95, start, end, step),
        "err_5xx_ratio": query_range(prom, Q_ERR_RATIO, start, end, step),
    }
    # Tout est agrégé -> au plus une série par requête. On indexe par timestamp.
    cols = {}
    for name, result in series.items():
        values = result[0]["values"] if result else []
        cols[name] = {int(ts): _num(v) for ts, v in values}

    timestamps = sorted(set().union(*[set(c) for c in cols.values()]))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        # La colonne `label` est un bonus pour l'évaluation du modèle ; Mahalia
        # peut la retirer (IsolationForest s'entraîne sur le profil normal seul).
        w.writerow(["timestamp", "req_rate", "p95_latency", "err_5xx_ratio", "label"])
        for ts in timestamps:
            w.writerow([
                ts,
                f"{cols['req_rate'].get(ts, 0.0):.4f}",
                f"{cols['p95_latency'].get(ts, 0.0):.4f}",
                f"{cols['err_5xx_ratio'].get(ts, 0.0):.4f}",
                label,
            ])
    print(f"✓ {len(timestamps)} points écrits dans {out} (label={label})")


def main():
    p = argparse.ArgumentParser(
        description="Mesure/export Prometheus pour le calibrage DoS.")
    p.add_argument("--prom", default="http://prometheus:9090",
                   help="URL Prometheus (défaut : service interne du compose).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("probe", help="Snapshot instantané par conteneur (live).")
    pp.add_argument("--watch", type=float, metavar="SEC",
                    help="Rafraîchit toutes les SEC secondes (Ctrl-C pour arrêter).")

    pr = sub.add_parser("range", help="Export CSV d'une fenêtre temporelle.")
    pr.add_argument("--start", required=True,
                    help="Epoch unix ou RFC3339 (ex : 1760000000).")
    pr.add_argument("--end", required=True)
    pr.add_argument("--step", default="5s")
    pr.add_argument("--label", required=True, choices=["normal", "attack"])
    pr.add_argument("--out", required=True)

    a = p.parse_args()
    if a.cmd == "probe":
        if a.watch:
            try:
                while True:
                    probe(a.prom)
                    time.sleep(a.watch)
            except KeyboardInterrupt:
                print("\n(arrêt)")
        else:
            probe(a.prom)
    elif a.cmd == "range":
        export_range(a.prom, a.start, a.end, a.step, a.label, a.out)


if __name__ == "__main__":
    main()
