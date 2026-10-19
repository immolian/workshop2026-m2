"""Tests payment-api — DB SQLite en mémoire, vérif JWT mockée (isole le service)."""
from fastapi.testclient import TestClient
import app as payment


def setup_module(_):
    payment.init_and_seed()


# On court-circuite la vérif distante vers auth pour tester payment-api seul.
payment.app.dependency_overrides[payment.require_auth] = lambda: {"valid": True, "sub": "demo"}
client = TestClient(payment.app)


def test_health_ok():
    assert client.get("/health").status_code == 200


def test_metrics_frozen_names():
    body = client.get("/metrics").text
    assert "http_requests_total" in body and "request_latency_seconds" in body


def test_balance_read():
    r = client.get("/balance/acc_demo")
    assert r.status_code == 200 and r.json()["account_id"] == "acc_demo"


def test_transaction_ok_debits_balance():
    before = client.get("/balance/acc_demo").json()["balance"]
    r = client.post("/transaction", json={"account_id": "acc_demo", "amount": 100})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    after = client.get("/balance/acc_demo").json()["balance"]
    assert round(before - after, 2) == 100.0


def test_transaction_insufficient_402():
    r = client.post("/transaction", json={"account_id": "acc_bob", "amount": 999999})
    assert r.status_code == 402


def test_transaction_unknown_account_404():
    r = client.post("/transaction", json={"account_id": "nope", "amount": 1})
    assert r.status_code == 404


def test_transaction_negative_422():
    r = client.post("/transaction", json={"account_id": "acc_demo", "amount": -5})
    assert r.status_code == 422


def test_auth_required():
    payment.app.dependency_overrides.clear()
    try:
        assert client.get("/balance/acc_demo").status_code == 401
    finally:
        payment.app.dependency_overrides[payment.require_auth] = lambda: {"valid": True}
