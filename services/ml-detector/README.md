# ml-detector — Model Card

## Features du modèle (IsolationForest)

Le modèle est entraîné sur 4 features, calculées via Prometheus (fenêtre glissante de 30s,
alignée sur `for:` des règles d'alerte) :

| Ordre | Feature | Requête PromQL (résumé) |
|---|---|---|
| 1 | `req_rate` | `sum(rate(http_requests_total{endpoint!~"/metrics|/health"}[30s]))` |
| 2 | `p95_latency` | `histogram_quantile(0.95, sum(rate(request_latency_seconds_bucket[30s])) by (le))` |
| 3 | `ratio_5xx` | part des status 5xx sur le total (hors /metrics, /health) |
| 4 | `ratio_4xx` | part des status 4xx sur le total (hors /metrics, /health) |

Détail des requêtes : voir `features.py`.

## Entraînement

- Modèle : `IsolationForest` (scikit-learn), entraîné uniquement sur trafic normal.
- Fichiers de données attendus : `data/normal.csv`, `data/flood.csv` (mêmes colonnes,
  mêmes requêtes PromQL que ci-dessus).
- Calibration : sigmoïde ancrée sur le 5e percentile du trafic normal (score ≈ 0.5)
  et la médiane des points en cœur d'attaque (score ≈ 0.95). Voir `train.py`.

## Résultat validé (20/10/2026)

- Trafic normal : score médian ≈ 0.15-0.4, 2% de points > 0.8 (bruit statistique isolé).
- Flood (`dos_flood.py`, 200 workers/30s) : score monte à 0.95, règle `AnomalyDetected`
  passe en `firing`.