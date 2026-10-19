"""
auth — STUB (owner: Gabriel)
À faire : vrai JWT signé (HS256 via JWT_SECRET), expiration, /auth/verify.
"""
import os
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="auth")
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_me")


@app.get("/health")
def health():
    return {"status": "ok"}


class Login(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(creds: Login):
    # STUB : ne vérifie rien encore. Renvoie un pseudo-token.
    return {"access_token": f"stub-token-for-{creds.username}", "token_type": "bearer"}
