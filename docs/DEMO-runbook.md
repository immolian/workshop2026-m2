# Runbook de démo — RESILIENCE-ALPHA

> Séquence VALIDÉE sur la VM (20/10). Reproduit la boucle de reprise autonome :
> attaque → détection → remédiation → nouvelle transaction OK, sans intervention
> humaine. À rejouer à l'identique pour les répétitions et la démo jury.

## Pré-requis (état de départ propre)
```bash
# sur la VM ws26-docker, à la racine du repo, à jour sur main
git pull origin main
docker compose up -d
docker compose ps          # tout "healthy"
```

## 1. Armer le moteur de remédiation
Dans `.env` (VM) : `DRY_RUN=false`, puis :
```bash
docker compose up -d remediation-engine
docker compose exec remediation-engine printenv DRY_RUN     # DOIT afficher: false
```
> Au quotidien (hors démo), remettre `DRY_RUN=true`.

## 2. Récupérer un token (compte seedé demo/demo123)
```bash
JWT=$(docker compose exec -T auth python -c "import urllib.request,json;d=json.dumps({'username':'demo','password':'demo123'}).encode();r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/auth/login',data=d,headers={'Content-Type':'application/json'}));print(json.load(r)['access_token'])")
echo "$JWT" | head -c 40; echo "..."     # doit afficher un début de JWT
```

## 3. Ouvrir la supervision
Dashboard Grafana : http://10.0.40.114:3000 → "RESILIENCE-ALPHA — Supervision & reprise"
(garder visible : débit, latence p95, anomaly_score, timeline remédiation)

## 4. Lancer l'attaque (DoS authentifié)
Depuis la VM cible (local) :
```bash
python3 attack/dos_flood.py --token "$JWT" --account acc_demo --concurrency 300 --duration 60
```
Depuis la VM d'attaque Kali (démo "PC attaquant distinct", une fois l'allowlist 10.0.40.0/24 ajoutée) :
```bash
python dos_flood.py --target http://10.0.40.114:8080 --endpoint /transaction --method POST --token "$JWT" --account acc_demo --concurrency 300 --duration 60
```

## 5. Ce qui doit se produire (preuve de reprise)
Dashboard : latence p95 franchit 0,5 s, anomaly_score franchit 0,8.
Logs moteur :
```bash
docker compose logs --tail=50 remediation-engine | grep -iE "alertname|decision|recovery"
```
Séquence attendue :
```
alert_received  AnomalyDetected (et/ou HighLatency)  firing
decision        execute   target: payment-api
recovery_confirmed   time_to_recover_s ≈ 3,7 s
```
Résultats mesurés : reprise en **3,67 s** (déclenchée par le ML seul) et **3,71 s**
(déclenchée par la latence). Les deux détecteurs convergent sur la même remédiation.

## 6. Entre deux essais : repartir propre
Le cooldown est de 60 s par cible. Pour rejouer vite :
```bash
docker compose restart payment-api remediation-engine
sleep 10
```
Reset complet (quand reset.yml de Claire sera prêt) : purge volumes + re-seed DB.

## Pièges connus
- **Flood sans token** → 100% de 401, n'atteint pas payment-api, ne déclenche rien.
  TOUJOURS passer `--token "$JWT"`.
- **anomaly_score plat à 0** → le conteneur ml-detector tourne le stub : rebuild
  `docker compose up -d --build ml-detector` (vérifier `model.joblib` dans /app).
- **decision: ignore / cooldown** → normal si <60 s depuis le dernier restart.
- **DRY_RUN non persistant** → vérifier avec `printenv DRY_RUN` AVANT chaque démo.
- **Durée du flood** : ≥45 s pour laisser l'alerte se déclencher (fenêtres 30 s + for 15s/10s).
