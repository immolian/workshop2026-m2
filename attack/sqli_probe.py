#!/usr/bin/env python3
"""Sonde d'injection SQL — owner: Gabriel. (Attaque SECONDAIRE, hors Clip Chrono.)

Envoie des charges SQLi classiques au WAF (port 8080). But : prouver que le WAF
les BLOQUE et que l'événement est journalisé (SIEM/Loki). Démontre l'interconnexion
des piliers (CYBER <-> INFRA <-> observabilité), PAS la reprise de disponibilité.

Défense en profondeur : même si une charge passe le WAF, payment-api utilise des
requêtes paramétrées (ORM) — aucune concaténation SQL, donc pas d'injection réelle.

PÉRIMÈTRE STRICT : SI fictif local uniquement (cf. _safety.py).

Usage :
  python3 attack/sqli_probe.py                    # $TARGET ou http://127.0.0.1:8080
  python3 attack/sqli_probe.py http://192.168.137.1:8080

Lecture du résultat :
  BLOQUÉ (WAF)   = 403/406/429  -> défense efficace (attendu une fois le WAF durci)
  ATTEINT L'APP  = 400/401/404/422 -> charge non filtrée par le WAF mais rejetée par l'app
  ACCEPTÉ (200)  -> à investiguer (ne devrait jamais arriver)
"""
import os
import sys

import httpx

from _safety import assert_target_in_scope

# Charges volontairement « manuel OWASP » : le but est qu'elles soient détectées.
PAYLOADS = [
    "' OR '1'='1",
    "' OR 1=1 --",
    "admin'--",
    "'; DROP TABLE users; --",
    "' UNION SELECT NULL,NULL --",
    "1) OR SLEEP(5)--",
]


def classify(status: int) -> str:
    if status in (403, 406, 429):
        return "BLOQUÉ (WAF)"
    if status in (400, 401, 404, 422):
        return "atteint l'app (rejeté)"
    if status == 200:
        return "ACCEPTÉ (!!)"
    return f"autre ({status})"


def probe(base: str) -> int:
    blocked = reached = other = 0
    with httpx.Client(timeout=10.0) as client:
        for p in PAYLOADS:
            results = []
            # 1) injection dans le chemin : GET /balance/<payload>
            try:
                r = client.get(f"{base}/balance/{p}")
                results.append(("GET /balance/<payload>", r.status_code))
            except Exception as e:  # noqa: BLE001
                results.append(("GET /balance/<payload>", f"err:{e.__class__.__name__}"))
            # 2) injection dans le corps : POST /transaction account_id=<payload>
            try:
                r = client.post(f"{base}/transaction",
                                json={"account_id": p, "amount": 1.0})
                results.append(("POST /transaction account_id", r.status_code))
            except Exception as e:  # noqa: BLE001
                results.append(("POST /transaction account_id", f"err:{e.__class__.__name__}"))

            print(f"\nPayload: {p!r}")
            for where, status in results:
                verdict = classify(status) if isinstance(status, int) else status
                print(f"   {where:32s} -> {status!s:>6}  {verdict}")
                if isinstance(status, int):
                    if verdict.startswith("BLOQUÉ"):
                        blocked += 1
                    elif status == 200:
                        other += 1
                    else:
                        reached += 1

    total = blocked + reached + other
    print("\n--- Bilan ---")
    print(f"  bloquées par le WAF : {blocked}/{total}")
    print(f"  atteignent l'app    : {reached}/{total}")
    print(f"  acceptées (200)     : {other}/{total}")
    if blocked == 0:
        print("\n[info] WAF en passthrough : aucune charge bloquée. Durcir le WAF"
              " (Coraza/ModSecurity + OWASP CRS) pour valider l'axe CYBER.")
    else:
        print("\n[ok] Le WAF bloque des charges : vérifier la trace dans Loki/SIEM.")
    # Code retour non-zéro si une charge a été ACCEPTÉE (200) : anomalie réelle.
    return 1 if other else 0


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET", "http://127.0.0.1:8080")).rstrip("/")
    assert_target_in_scope(base)
    print(f"Sonde SQLi sur {base} — {len(PAYLOADS)} charges x 2 vecteurs")
    sys.exit(probe(base))


if __name__ == "__main__":
    main()
