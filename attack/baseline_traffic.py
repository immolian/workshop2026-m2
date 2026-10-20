#!/usr/bin/env python3
"""
baseline_traffic.py — Génère un trafic LÉGITIME léger (profil "situation ordinaire").

But : alimenter Prometheus en requêtes authentifiées normales pendant ~3 min pour
capturer la baseline (Tâche 1 du calibrage). Rien d'offensif : ce sont de vraies
transactions fictives, au rythme d'un usage calme (quelques req/s).

À lancer depuis le PC Attaquant ou l'hôte, vers le point d'entrée public (le WAF).
Dépendances : stdlib uniquement.

ADAPTE si besoin aux schémas réels de ton API (voir les 3 commentaires # ADAPTER).
"""
import argparse
import json
import random
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

# ADAPTER : identifiants de comptes seedés tels que ton API les attend.
SEEDED_ACCOUNTS = ["demo", "operator"]  # on laisse canary-remediation au canari


def _post(url, body, token=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.load(r)


def _get(url, token=None):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.load(r)


def login(base, user, password):
    # ADAPTER : noms des champs du payload de login si différents.
    _, body = _post(f"{base}/auth/login",
                    {"username": user, "password": password})
    token = body.get("access_token") or body.get("token")
    if not token:
        sys.exit(f"Login OK mais aucun token trouvé dans la réponse : {body}")
    return token


def run(base, user, password, rate, duration):
    token = login(base, user, password)
    interval = 1.0 / rate
    deadline = time.time() + duration
    ok = err = 0
    while time.time() < deadline:
        try:
            if random.random() < 0.5:
                _get(f"{base}/balance/{random.choice(SEEDED_ACCOUNTS)}", token)
            else:
                # ADAPTER : schéma du POST /transaction.
                _post(f"{base}/transaction", {
                    "from_account": "demo",
                    "to_account": "operator",
                    "amount": round(random.uniform(1, 50), 2),
                }, token)
            ok += 1
        except (HTTPError, URLError) as e:
            err += 1
            print(f"  (requête en échec : {e})", file=sys.stderr)
        time.sleep(interval)
    print(f"✓ Baseline terminée : {ok} requêtes OK, {err} en échec "
          f"(~{rate} req/s pendant {duration}s)")


def main():
    p = argparse.ArgumentParser(
        description="Trafic légitime léger pour la baseline Prometheus.")
    p.add_argument("--target", required=True,
                   help="URL de base via le WAF (ex : http://192.168.137.1:8080).")
    p.add_argument("--user", default="demo")
    p.add_argument("--password", default="demo123")
    p.add_argument("--rate", type=float, default=2.0,
                   help="Requêtes/seconde (défaut 2).")
    p.add_argument("--duration", type=int, default=180,
                   help="Durée en secondes (défaut 180).")
    a = p.parse_args()
    run(a.target, a.user, a.password, a.rate, a.duration)


if __name__ == "__main__":
    main()
