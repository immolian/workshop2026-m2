# Scénarios offensifs — owner: Gabriel

**PÉRIMÈTRE STRICT** : uniquement le SI fictif du groupe, sur le réseau du
consortium (`127.0.0.1` ou `192.168.137.0/24`). Jamais le campus, un autre
groupe ou un service tiers. Les deux scripts intègrent un garde-fou
(`_safety.py`) qui **refuse de s'exécuter contre une cible hors-périmètre**.

## Primaire (démontré au Clip Chrono) : DoS applicatif
`dos_flood.py` — flood concurrent de `POST /transaction` via le WAF (port 8080).
Effet observable : montée du rate + latence (+ 5xx sous saturation) -> alerte
Prometheus -> remédiation automatique.

```bash
python3 attack/dos_flood.py                          # localhost:8080 par défaut
python3 attack/dos_flood.py http://192.168.137.1:8080
python3 attack/dos_flood.py --concurrency 400 --duration 30
python3 attack/dos_flood.py --token "<JWT>"          # charge aussi auth+DB -> 5xx
```

**Calibrage** (exigence du sujet) : le script affiche rps / latence p50-p95 /
5xx par seconde. Montez `--concurrency` par paliers jusqu'à franchir les seuils
des règles (`HighErrorRate` : 5xx > 25 % ; `AnomalyDetected` : score ML > 0.8).
Sans token, le flood génère surtout des 401 + une forte hausse rate/latence
(chemin de détection ML). Avec `--token` valide, chaque requête fait appeler
`auth/verify` → sature auth → 503 sur payment-api (déclenche `HighErrorRate`).

## Secondaire (Axe 2, hors Clip Chrono) : injection SQL
`sqli_probe.py` — envoie des charges SQLi classiques au WAF (chemin + corps).
But : prouver que le WAF les **bloque** et que l'événement est **journalisé**
(SIEM/Loki). Démontre l'interconnexion des piliers, **pas** la reprise.

```bash
python3 attack/sqli_probe.py
python3 attack/sqli_probe.py http://192.168.137.1:8080
```

Lecture : `403/406/429` = bloqué par le WAF (attendu une fois le WAF durci avec
Coraza/ModSecurity + OWASP CRS) ; `400/401/404/422` = atteint l'app mais rejeté ;
`200` = anomalie à investiguer. Défense en profondeur : `payment-api` n'utilise
que des requêtes paramétrées (ORM), donc aucune injection réelle même sans WAF.

## Dépendances
```bash
pip install -r attack/requirements.txt
```
