"""Seed dev buyers + activity for the admin panel.

Run with: `python -m backend.tests.seed_admin_dev_data` from /app or
`python tests/seed_admin_dev_data.py` from /app/backend.

Idempotent — re-running won't duplicate buyers (upsert by email) and
appends fresh dated activity rows each run so the chart shows movement.
"""
import asyncio
import os
import random
import uuid
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

SAMPLE_BUYERS = [
    {"email": "alex.morgan@example.com", "entitlements": ["base", "shorts", "studio"], "totalSpendCents": 49700, "loginCount": 14, "scriptCount": 22, "shortsCount": 8},
    {"email": "jamie.lin@example.com", "entitlements": ["base", "studio"], "totalSpendCents": 29700, "loginCount": 9, "scriptCount": 11, "shortsCount": 0},
    {"email": "priya.shah@example.com", "entitlements": ["base", "shorts"], "totalSpendCents": 19400, "loginCount": 22, "scriptCount": 31, "shortsCount": 12},
    {"email": "marcus.young@example.com", "entitlements": ["base"], "totalSpendCents": 9700, "loginCount": 4, "scriptCount": 5, "shortsCount": 0},
    {"email": "sarah.cole@example.com", "entitlements": ["base", "shorts", "studio"], "totalSpendCents": 49700, "loginCount": 31, "scriptCount": 47, "shortsCount": 18},
    {"email": "dev.testing@example.com", "entitlements": ["base"], "totalSpendCents": 0, "loginCount": 1, "scriptCount": 0, "shortsCount": 0},
]


async def main():
    mongo = AsyncIOMotorClient(MONGO_URL)
    db = mongo[DB_NAME]
    now = datetime.now(timezone.utc)

    for i, b in enumerate(SAMPLE_BUYERS):
        added = (now - timedelta(days=random.randint(2, 60))).isoformat()
        last_login = (now - timedelta(days=random.randint(0, 14))).isoformat()
        await db.buyers.update_one(
            {"email": b["email"]},
            {
                "$set": {
                    **b,
                    "seenOrderIds": [f"seed-{i}-{j}" for j in range(2)],
                    "lastLoginAt": last_login,
                    "firstUseAt": added,
                    "source": "seed",
                    "updatedAt": now.isoformat(),
                },
                "$setOnInsert": {"addedAt": added},
            },
            upsert=True,
        )
        print(f"  upsert buyer  {b['email']}")

    # Seed a few activity rows including a webhook_failed for Replay button demo.
    events = [
        ("webhook", "alex.morgan@example.com", {"status": "ok", "product": "studio", "order_id": "po_demo_1"}),
        ("webhook", "jamie.lin@example.com", {"status": "ok", "product": "shorts", "order_id": "po_demo_2"}),
        ("webhook_failed", "broken-email", {
            "reason": "unknown product",
            "product": "lifetime",
            "payload": {"email": "broken-email", "total_amount": "4700", "order_id": "po_demo_3"},
            "source": "pinball",
        }),
        ("admin_grant", "drcharitycampbell@gmail.com", {"buyer": "marcus.young@example.com", "entitlement": "shorts"}),
        ("studio_render", "sarah.cole@example.com", {"mode": "faceless", "aspect": "9_16"}),
    ]
    for typ, email, detail in events:
        ts = (now - timedelta(hours=random.randint(1, 240))).isoformat()
        await db.activity.insert_one({
            "id": str(uuid.uuid4()),
            "ts": ts,
            "type": typ,
            "email": email,
            "detail": detail,
        })
    print(f"  + {len(events)} activity rows")

    print("\nSeed complete.")
    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
