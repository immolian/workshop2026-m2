"""Simule du trafic normal : connexion + consultations/transactions sur acc_demo."""
import asyncio
import random
import httpx

AUTH_URL = "http://auth:8000"
API_URL = "http://payment-api:8000"


async def get_token(client: httpx.AsyncClient) -> str:
    r = await client.post(f"{AUTH_URL}/auth/login",
                           json={"username": "demo", "password": "demo123"})
    r.raise_for_status()
    return r.json()["access_token"]


async def worker(client: httpx.AsyncClient, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        try:
            # Uniquement de la consultation : ne débite jamais, pas de risque d'épuiser un solde.
            await client.get(f"{API_URL}/balance/acc_bob", headers=headers, timeout=3)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.3, 1.5))
        
async def main():
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        await asyncio.gather(*[worker(client, token) for _ in range(3)])


if __name__ == "__main__":
    print("Trafic normal en cours... (Ctrl+C pour arrêter)")
    asyncio.run(main())