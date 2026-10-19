import os
import math
import httpx

PROM = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")

# Fenêtre de 30s pour coller au "for: 10s" de la règle AnomalyDetected
# On exclut /metrics et /health du débit : ce sont les sondes, pas de vrais clients.
QUERIES = {
    "req_rate":
        'sum(rate(http_requests_total{endpoint!~"/metrics|/health"}[30s]))',
    "p95_latency":
        'histogram_quantile(0.95, sum(rate(request_latency_seconds_bucket[30s])) by (le))',
    "ratio_5xx":
        'sum(rate(http_requests_total{status=~"5..",endpoint!~"/metrics|/health"}[30s])) '
        '/ sum(rate(http_requests_total{endpoint!~"/metrics|/health"}[30s]))',
    "ratio_4xx":
        'sum(rate(http_requests_total{status=~"4..",endpoint!~"/metrics|/health"}[30s])) '
        '/ sum(rate(http_requests_total{endpoint!~"/metrics|/health"}[30s]))',
}
FEATURES = list(QUERIES)  # ordre fixe, utilisé partout


def query(promql: str) -> float:
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": promql}, timeout=5)
    r.raise_for_status()
    result = r.json()["data"]["result"]
    if not result:
        return 0.0
    v = float(result[0]["value"][1])
    return 0.0 if (math.isnan(v) or math.isinf(v)) else v


def fetch_features() -> list[float]:
    return [query(QUERIES[name]) for name in FEATURES]


if __name__ == "__main__":
    print(dict(zip(FEATURES, fetch_features())))