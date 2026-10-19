"""Simule du trafic normal : connexion + transactions régulières sur acc_demo."""
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
            await client.post(
                f"{API_URL}/transaction",
                json={"account_id": "acc_demo", "amount": round(random.uniform(1, 20), 2)},
                headers=headers,
                timeout=3,
            )
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.3, 1.5))  # rythme variable, réaliste


async def main():
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        # 3 "utilisateurs" en parallèle, avec un peu de variation de rythme
        await asyncio.gather(*[worker(client, token) for _ in range(3)])


if __name__ == "__main__":
    print("Trafic normal en cours... (Ctrl+C pour arrêter)")
    asyncio.run(main())