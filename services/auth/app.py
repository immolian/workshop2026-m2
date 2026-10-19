"""
auth — owner: Gabriel
Service d'authentification. Émet des JWT HS256 signés (JWT_SECRET), valide des
identifiants contre une table users seedée, et expose /auth/verify consommé par
payment-api.

Stockage : par défaut SQLite local (service autonome, re-seedé au boot — robuste
au restart de la démo). Pour partager le PostgreSQL `payment`, l'infra ajoute
DATABASE_URL (+ SEED_USERS) au service auth dans docker-compose.yml : le code
fonctionne sans modification dans les deux cas.

Endpoints : GET /health, GET /metrics, POST /auth/login, POST /auth/verify
Métriques : http_requests_total{method,endpoint,status}, request_latency_seconds{endpoint}
Conteneur : auth  (réseau interne uniquement, non exposé via le WAF)
"""
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, Request, Response, HTTPException
from pydantic import BaseModel
from passlib.context import CryptContext
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import create_engine, String, DateTime, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy.exc import OperationalError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [auth] %(message)s")
log = logging.getLogger("auth")

# --- Configuration -------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_me")   # prod -> SOPS/Vault
JWT_ALG = "HS256"
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "3600"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/auth.db")
SEED_USERS = os.getenv("SEED_USERS", "demo:demo123,operator:operator123")

# --- Métriques FIGÉES (mêmes noms/labels que payment-api) ----------------------
REQUESTS = Counter("http_requests_total", "Total HTTP requests",
                   ["method", "endpoint", "status"])
LATENCY = Histogram("request_latency_seconds", "Request latency", ["endpoint"])
_KNOWN = {"/health", "/metrics", "/auth/login", "/auth/verify"}

# --- Sécurité (hash mdp + JWT) -------------------------------------------------
_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")  # pur Python


def hash_password(p: str) -> str:
    return _pwd.hash(p)


def verify_password(p: str, h: str) -> bool:
    return _pwd.verify(p, h)


def issue_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "iat": int(now.timestamp()),
               "exp": int((now + timedelta(seconds=JWT_TTL_SECONDS)).timestamp())}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


# --- Base de données -----------------------------------------------------------
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    Base.metadata.create_all(bind=engine)
    pairs = [p for p in SEED_USERS.split(",") if ":" in p]
    with SessionLocal() as s:
        for pair in pairs:
            username, password = pair.split(":", 1)
            username = username.strip()
            if username and not s.query(User).filter_by(username=username).first():
                s.add(User(username=username, password_hash=hash_password(password.strip())))
                log.info("Utilisateur seedé: %s", username)
        s.commit()


# --- Application ---------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    init_and_seed()
    log.info("auth prêt (db=%s).", engine.dialect.name)
    yield


app = FastAPI(title="auth", lifespan=lifespan)


@app.middleware("http")
async def instrument(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    endpoint = request.url.path if request.url.path in _KNOWN else "other"
    LATENCY.labels(endpoint).observe(elapsed)
    REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
    return response


class Login(BaseModel):
    username: str
    password: str


class VerifyIn(BaseModel):
    token: str


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


@app.post("/auth/login")
def login(creds: Login):
    with SessionLocal() as s:
        user = s.query(User).filter_by(username=creds.username).first()
        if not user or not verify_password(creds.password, user.password_hash):
            raise HTTPException(status_code=401, detail="identifiants invalides")
    return {"access_token": issue_token(creds.username), "token_type": "bearer"}


@app.post("/auth/verify")
def verify(body: VerifyIn):
    try:
        payload = jwt.decode(body.token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expiré")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="token invalide")
    return {"valid": True, "sub": payload.get("sub")}
