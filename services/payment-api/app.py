"""
payment-api — owner: Gabriel
SI de paiement fictif (support métier minimal). Persiste les transactions en
PostgreSQL, vérifie les JWT auprès du service auth, expose les métriques figées.

CONTRAT FIGÉ (ne pas changer sans accord équipe — détection + remédiation + ML
en dépendent) :
  Endpoints : GET /health, GET /metrics, POST /transaction, GET /balance/{account_id}
  Métriques : http_requests_total{method,endpoint,status}
              request_latency_seconds (histogram, label: endpoint)
  Conteneur : payment-api   |   DB : db (réseau interne, jamais publiée)
"""
import os
import time
import logging
from decimal import Decimal, InvalidOperation
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Header, Depends
from pydantic import BaseModel, field_validator
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import create_engine, String, Numeric, DateTime, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy.exc import OperationalError
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [payment-api] %(message)s")
log = logging.getLogger("payment-api")

# --- Configuration (tout depuis l'environnement, aucun secret en dur) ----------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./payment-dev.db")
AUTH_URL = os.getenv("AUTH_URL", "http://auth:8000")          # fourni par compose
AUTH_TIMEOUT = float(os.getenv("AUTH_TIMEOUT", "2.0"))
# Comptes seedés au 1er démarrage (démo). Format id:solde
SEED_ACCOUNTS = os.getenv("SEED_ACCOUNTS", "acc_demo:100000.00,acc_bob:500.00")

# --- Métriques FIGÉES (consommées par Prometheus -> alertes -> remédiation) ----
# Noms et labels identiques au stub d'origine. On normalise seulement la VALEUR
# du label endpoint (/balance/<id> -> /balance/{account_id}) pour éviter une
# explosion de cardinalité sous flood ; les noms/labels du contrat sont intacts.
REQUESTS = Counter("http_requests_total", "Total HTTP requests",
                   ["method", "endpoint", "status"])
LATENCY = Histogram("request_latency_seconds", "Request latency", ["endpoint"])


def _endpoint_label(path: str) -> str:
    if path.startswith("/balance/"):
        return "/balance/{account_id}"
    if path in ("/health", "/metrics", "/transaction"):
        return path
    return "other"


# --- Base de données -----------------------------------------------------------
class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Account(Base):
    __tablename__ = "accounts"
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | declined
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def _make_engine(url: str):
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def wait_for_db(max_tries: int = 30, delay: float = 1.0) -> None:
    for attempt in range(1, max_tries + 1):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except OperationalError as exc:
            log.warning("DB indisponible (%s/%s): %s", attempt, max_tries, exc)
            time.sleep(delay)
    raise RuntimeError("DB injoignable après plusieurs tentatives.")


def init_and_seed() -> None:
    Base.metadata.create_all(bind=engine)          # idempotent (cohabite avec auth)
    pairs = [p for p in SEED_ACCOUNTS.split(",") if ":" in p]
    with SessionLocal() as s:
        for pair in pairs:
            acc_id, bal = pair.split(":", 1)
            acc_id = acc_id.strip()
            if acc_id and not s.get(Account, acc_id):
                s.add(Account(account_id=acc_id, balance=Decimal(bal.strip())))
                log.info("Compte seedé: %s (%s)", acc_id, bal)
        s.commit()


# --- Vérification JWT auprès du service auth (interconnexion DEV/CYBER) ---------
def require_auth(authorization: str = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="token Bearer manquant")
    token = authorization.split(" ", 1)[1].strip()
    try:
        r = httpx.post(f"{AUTH_URL}/auth/verify", json={"token": token}, timeout=AUTH_TIMEOUT)
    except httpx.RequestError:
        # auth injoignable -> dépendance dégradée (503), pas un échec d'auth.
        raise HTTPException(status_code=503, detail="service auth indisponible")
    if r.status_code == 200 and r.json().get("valid"):
        return r.json()
    raise HTTPException(status_code=401, detail="token invalide")


# --- Application ---------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    init_and_seed()
    log.info("payment-api prêt (db=%s, auth=%s).", engine.dialect.name, AUTH_URL)
    yield


app = FastAPI(title="payment-api", lifespan=lifespan)


@app.middleware("http")
async def instrument(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    endpoint = _endpoint_label(request.url.path)
    LATENCY.labels(endpoint).observe(elapsed)
    REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
    return response


class TransactionIn(BaseModel):
    account_id: str
    amount: Decimal
    currency: str = "EUR"

    @field_validator("amount")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("montant strictement positif requis")
        return v


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db indisponible: {exc}")
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/transaction")
def create_transaction(tx: TransactionIn, _auth=Depends(require_auth)):
    with SessionLocal() as s:
        acc = s.get(Account, tx.account_id, with_for_update=True) \
            if engine.dialect.name != "sqlite" else s.get(Account, tx.account_id)
        if acc is None:
            raise HTTPException(status_code=404, detail="compte inconnu")
        if Decimal(acc.balance) < tx.amount:
            s.add(Transaction(account_id=tx.account_id, amount=tx.amount,
                              currency=tx.currency, status="declined"))
            s.commit()
            raise HTTPException(status_code=402, detail="solde insuffisant")
        acc.balance = Decimal(acc.balance) - tx.amount
        row = Transaction(account_id=tx.account_id, amount=tx.amount,
                          currency=tx.currency, status="ok")
        s.add(row)
        s.commit()
        s.refresh(row)
        return {"status": "ok", "tx_id": str(row.id), "account_id": tx.account_id,
                "amount": float(tx.amount), "currency": tx.currency}


@app.get("/balance/{account_id}")
def balance(account_id: str, _auth=Depends(require_auth)):
    with SessionLocal() as s:
        acc = s.get(Account, account_id)
        if acc is None:
            raise HTTPException(status_code=404, detail="compte inconnu")
        return {"account_id": acc.account_id, "balance": float(acc.balance),
                "currency": acc.currency}
