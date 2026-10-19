"""Tests auth — login réel, émission + vérification de JWT HS256."""
from fastapi.testclient import TestClient
import app as auth


def setup_module(_):
    auth.init_and_seed()


client = TestClient(auth.app)


def test_health_ok():
    assert client.get("/health").status_code == 200


def test_metrics_frozen_names():
    body = client.get("/metrics").text
    assert "http_requests_total" in body and "request_latency_seconds" in body


def test_login_ok():
    r = client.post("/auth/login", json={"username": "demo", "password": "demo123"})
    assert r.status_code == 200 and r.json()["access_token"]


def test_login_bad_password_401():
    r = client.post("/auth/login", json={"username": "demo", "password": "x"})
    assert r.status_code == 401


def test_login_unknown_user_401():
    r = client.post("/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_verify_roundtrip():
    tok = client.post("/auth/login", json={"username": "demo", "password": "demo123"}).json()["access_token"]
    r = client.post("/auth/verify", json={"token": tok})
    assert r.status_code == 200 and r.json() == {"valid": True, "sub": "demo"}


def test_verify_rejects_garbage():
    assert client.post("/auth/verify", json={"token": "not.a.jwt"}).status_code == 401
