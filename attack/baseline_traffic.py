#!/usr/bin/env python3
"""
baseline_traffic.py — Génère un trafic LÉGITIME léger (profil "situation ordinaire").

But : alimenter Prometheus en requêtes authentifiées normales pendant ~3 min pour
capturer la baseline (Tâche 1 du calibrage). Rien d'offensif : ce sont de vraies
transactions fictives, au rythme d'un usage calme (quelques req/s).

À lancer depuis le PC Attaquant ou l'hôte, vers le point d'entrée public (le WAF).
Dépendances : stdlib uniquement.

Schémas alignés sur payment-api/auth (POST /transaction = account_id+amount,
comptes acc_demo/acc_bob, login username/password).
"""
import argparse
import json
import random
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

# Identifiants de comptes seedés tels que payment-api les attend (voir SEED_ACCOUNTS
# dans services/payment-api/app.py). Ce sont des ACCOUNT_ID, à ne pas confondre avec
# les noms d'utilisateur du login (demo/operator). On laisse canary-remediation au
# canari du remediation-engine.
SEEDED_ACCOUNTS = ["acc_demo", "acc_bob"]
# Compte à solde élevé (100 000) réservé aux POST /transaction, pour éviter que le
# baseline ne se pollue de 402 "solde insuffisant" (acc_bob n'a que 500).
TX_ACCOUNT = "acc_demo"


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
    # Aligné sur auth : payload {username, password}, réponse {access_token}.
    _, body = _post(f"{base}/auth/login",
                    {"username": user, "password": password})
    token = body.get("access_token") or body.get("token")
    if not token:
        sys.exit(f"Login OK mais aucun token trouvé dans la réponse : {body}")
    return token


def run(base, user, password, rate, duration, token=None):
    # Si un token est fourni (ex. auth non exposé via le WAF), on saute le login.
    if not token:
        token = login(base, user, password)
    interval = 1.0 / rate
    deadline = time.time() + duration
    ok = err = 0
    while time.time() < deadline:
        try:
            if random.random() < 0.5:
                _get(f"{base}/balance/{random.choice(SEEDED_ACCOUNTS)}", token)
            else:
                # Schéma réel de payment-api : account_id + amount (currency -> EUR
                # par défaut). Pas de from_account/to_account.
                _post(f"{base}/transaction", {
                    "account_id": TX_ACCOUNT,
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
    p.add_argument("--token", default=None,
                   help="JWT déjà obtenu ; court-circuite le login (auth non exposé).")
    p.add_argument("--rate", type=float, default=2.0,
                   help="Requêtes/seconde (défaut 2).")
    p.add_argument("--duration", type=int, default=180,
                   help="Durée en secondes (défaut 180).")
    a = p.parse_args()
    run(a.target, a.user, a.password, a.rate, a.duration, a.token)


if __name__ == "__main__":
    main()
