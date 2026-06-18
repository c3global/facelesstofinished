"""Pytest suite for the admin panel + buyer import + Pinball webhook.

Strict scope: token gate, dedupe, union-merge, max() counters, replay,
admin endpoint isAdmin gating. ZERO real API spend — uses a mock httpx
network shim (none of these endpoints reach external services).

Run: `cd /app && pytest backend/tests/test_admin_pinball.py -v`
"""
import os
import uuid
import asyncio
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "f48_studio_test")
os.environ.setdefault("PINBALL_WEBHOOK_TOKEN", "test-token-xyz")
os.environ.setdefault("ADMIN_EMAILS", "admin@example.com")
os.environ.setdefault("DEV_BYPASS_EMAIL", "")
os.environ.setdefault("NETLIFY_AUTH_URL", "")
os.environ.setdefault("STUDIO_GRANT_EMAILS", "admin@example.com,buyer@example.com")
os.environ.setdefault("JWT_SECRET", "test-secret")

import sys
sys.path.insert(0, "/app/backend")

# Reload module since PINBALL_WEBHOOK_TOKEN is read at import time inside admin_routes
import importlib
import admin_routes
importlib.reload(admin_routes)
import server
importlib.reload(server)
from server import app, db  # noqa: E402
from admin_routes import PINBALL_WEBHOOK_TOKEN  # noqa: E402


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_db():
    await db.buyers.delete_many({})
    await db.activity.delete_many({})
    yield
    await db.buyers.delete_many({})
    await db.activity.delete_many({})


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client: AsyncClient, email: str) -> str:
    r = await client.post("/api/auth/check", json={"email": email})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------------------------------------------------------------------------
# Pinball webhook
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pinball_bad_token_logs_and_rejects(client):
    r = await client.post(
        "/api/pinball-webhook?token=WRONG&product=studio",
        json={"email": "buyer@example.com", "total_amount": "4700", "order_id": "po_1"},
    )
    assert r.status_code == 401
    fail = await db.activity.find_one({"type": "webhook_failed"})
    assert fail is not None
    assert fail["detail"]["reason"] == "invalid token"


@pytest.mark.asyncio
async def test_pinball_creates_buyer_with_studio_lifetime(client):
    r = await client.post(
        f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=studio",
        json={"email": "Buyer@Example.com", "total_amount": "29700", "order_id": "po_alpha"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    doc = await db.buyers.find_one({"email": "buyer@example.com"})
    assert doc is not None
    assert "studio" in doc["entitlements"]
    assert doc["studio_lifetime"] is True
    assert doc["studio_status"] == "active"
    assert doc["studio_current_period_end"] == "2099-01-01T00:00:00Z"
    assert "po_alpha" in doc["seenOrderIds"]
    assert doc["totalSpendCents"] == 29700


@pytest.mark.asyncio
async def test_pinball_dedupes_same_order_id(client):
    payload = {"email": "buyer@example.com", "total_amount": "4700", "order_id": "po_dup"}
    r1 = await client.post(f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=base", json=payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"
    r2 = await client.post(f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=base", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    doc = await db.buyers.find_one({"email": "buyer@example.com"})
    # Spend not double-counted
    assert doc["totalSpendCents"] == 4700


@pytest.mark.asyncio
async def test_pinball_union_merges_entitlements(client):
    p1 = {"email": "buyer@example.com", "total_amount": "1000", "order_id": "o1"}
    p2 = {"email": "buyer@example.com", "total_amount": "2000", "order_id": "o2"}
    await client.post(f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=base", json=p1)
    await client.post(f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=shorts", json=p2)
    doc = await db.buyers.find_one({"email": "buyer@example.com"})
    assert set(doc["entitlements"]) == {"base", "shorts"}
    assert doc["totalSpendCents"] == 3000
    assert set(doc["seenOrderIds"]) == {"o1", "o2"}


@pytest.mark.asyncio
async def test_pinball_unknown_product_rejected(client):
    r = await client.post(
        f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=lifetime",
        json={"email": "buyer@example.com", "total_amount": "10000", "order_id": "x"},
    )
    assert r.status_code == 400
    fail = await db.activity.find_one({"type": "webhook_failed"})
    assert fail["detail"]["reason"] == "unknown product"


@pytest.mark.asyncio
async def test_pinball_missing_email_rejected(client):
    r = await client.post(
        f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=base",
        json={"total_amount": "10000", "order_id": "x"},
    )
    assert r.status_code == 400
    fail = await db.activity.find_one({"type": "webhook_failed"})
    assert fail["detail"]["reason"] == "missing or malformed email"


# ---------------------------------------------------------------------------
# Admin endpoints — auth gate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_endpoints_require_admin(client):
    # No auth → 401
    r = await client.get("/api/admin/buyers")
    assert r.status_code == 401

    # Non-admin user → 403. We need an email that is in STUDIO_GRANT_EMAILS
    # but not in ADMIN_EMAILS so the JWT issues with isAdmin=False.
    token = await _login(client, "buyer@example.com")
    r2 = await client.get("/api/admin/buyers", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 403

    # Admin → 200
    admin_token = await _login(client, "admin@example.com")
    r3 = await client.get("/api/admin/buyers", headers={"Authorization": f"Bearer {admin_token}"})
    assert r3.status_code == 200


# ---------------------------------------------------------------------------
# Buyer CRUD
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_grant_revoke_delete(client):
    token = await _login(client, "admin@example.com")
    h = {"Authorization": f"Bearer {token}"}

    # Grant — auto-creates buyer
    r = await client.patch("/api/admin/buyers/new@example.com/grant", json={"entitlement": "base"}, headers=h)
    assert r.status_code == 200
    assert "base" in r.json()["buyer"]["entitlements"]

    # Grant adds; doesn't overwrite
    r = await client.patch("/api/admin/buyers/new@example.com/grant", json={"entitlement": "shorts"}, headers=h)
    assert set(r.json()["buyer"]["entitlements"]) == {"base", "shorts"}

    # Revoke
    r = await client.patch("/api/admin/buyers/new@example.com/revoke", json={"entitlement": "base"}, headers=h)
    assert r.status_code == 200
    assert r.json()["buyer"]["entitlements"] == ["shorts"]

    # Unknown entitlement → 400
    r = await client.patch("/api/admin/buyers/new@example.com/grant", json={"entitlement": "premium"}, headers=h)
    assert r.status_code == 400

    # Delete
    r = await client.delete("/api/admin/buyers/new@example.com", headers=h)
    assert r.status_code == 200
    assert (await db.buyers.find_one({"email": "new@example.com"})) is None


@pytest.mark.asyncio
async def test_admin_bulk_delete(client):
    token = await _login(client, "admin@example.com")
    h = {"Authorization": f"Bearer {token}"}
    for e in ["a@ex.com", "b@ex.com", "c@ex.com"]:
        await db.buyers.insert_one({"email": e, "entitlements": ["base"], "addedAt": "2026-01-01T00:00:00Z"})

    r = await client.post("/api/admin/buyers/bulk-delete", json={"emails": ["a@ex.com", "c@ex.com"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
    remaining = [d["email"] async for d in db.buyers.find({})]
    assert remaining == ["b@ex.com"]


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_import_creates_and_merges(client):
    token = await _login(client, "admin@example.com")
    h = {"Authorization": f"Bearer {token}"}

    # Seed an existing buyer with partial data
    await db.buyers.insert_one({
        "email": "merge@example.com",
        "entitlements": ["base"],
        "totalSpendCents": 5000,
        "seenOrderIds": ["po_existing"],
        "loginCount": 5,
        "scriptCount": 3,
        "shortsCount": 0,
        "addedAt": "2026-01-15T00:00:00Z",  # earlier
        "firstUseAt": "2026-01-20T00:00:00Z",
        "lastLoginAt": "2026-02-01T00:00:00Z",
    })

    payload = {
        "buyers": [
            {
                # New buyer
                "email": "newone@example.com",
                "entitlements": ["base", "shorts"],
                "totalSpendCents": 9700,
                "seenOrderIds": ["po_new"],
                "orderId": "po_new",
                "addedAt": "2026-02-10T00:00:00Z",
                "lastLoginAt": "2026-02-12T00:00:00Z",
                "loginCount": 3,
                "scriptCount": 1,
                "shortsCount": 0,
                "firstUseAt": "2026-02-11T00:00:00Z",
                "source": "netlify-import",
                "event": None,
            },
            {
                # Merge with existing
                "email": "MERGE@example.com",   # case differs — lowercase'd internally
                "entitlements": ["shorts", "studio"],   # base from existing, union → {base, shorts, studio}
                "totalSpendCents": 3000,        # less than existing's 5000 → max() wins → 5000 stays
                "seenOrderIds": ["po_new2"],    # union with existing
                "addedAt": "2026-02-01T00:00:00Z",  # later than existing's Jan 15 → min wins → keep Jan 15
                "lastLoginAt": "2026-02-15T00:00:00Z",  # later than Feb 1 → max wins
                "loginCount": 12,               # higher than 5 → max wins
                "scriptCount": 1,               # lower than 3 → max keeps 3
                "shortsCount": 7,               # higher than 0 → max wins
                "firstUseAt": None,             # null — must not overwrite Jan 20
            },
            {
                # Bad row (invalid email)
                "email": "not-an-email",
                "entitlements": ["base"],
            },
        ]
    }

    r = await client.post("/api/admin/buyers/import", json=payload, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 1
    assert body["merged"] == 1
    assert body["skipped"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["email"] == "not-an-email"

    new_doc = await db.buyers.find_one({"email": "newone@example.com"})
    assert set(new_doc["entitlements"]) == {"base", "shorts"}

    merged_doc = await db.buyers.find_one({"email": "merge@example.com"})
    assert set(merged_doc["entitlements"]) == {"base", "shorts", "studio"}
    assert merged_doc["totalSpendCents"] == 5000     # max kept existing
    assert merged_doc["loginCount"] == 12            # max picked new
    assert merged_doc["scriptCount"] == 3            # max kept existing
    assert merged_doc["shortsCount"] == 7
    assert merged_doc["addedAt"] == "2026-01-15T00:00:00Z"  # earlier wins
    assert merged_doc["lastLoginAt"] == "2026-02-15T00:00:00Z"  # later wins
    assert merged_doc["firstUseAt"] == "2026-01-20T00:00:00Z"  # null didn't overwrite
    assert set(merged_doc["seenOrderIds"]) == {"po_existing", "po_new2"}


# ---------------------------------------------------------------------------
# Activity + Replay
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_activity_filter_and_replay(client):
    token = await _login(client, "admin@example.com")
    h = {"Authorization": f"Bearer {token}"}

    # Submit a webhook with an unknown product so it logs as webhook_failed.
    await client.post(
        f"/api/pinball-webhook?token={PINBALL_WEBHOOK_TOKEN}&product=lifetime",
        json={"email": "replay@example.com", "total_amount": "1000", "order_id": "po_replay"},
    )

    # Listing should include it; filter by type=webhook_failed
    r = await client.get("/api/admin/activity?type=webhook_failed", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    failed = items[0]
    assert failed["type"] == "webhook_failed"

    # Cannot replay because original product was "lifetime" (unknown) → 400
    r = await client.post(f"/api/admin/activity/{failed['id']}/replay", headers=h)
    assert r.status_code == 400

    # Now inject a webhook_failed with a VALID product so replay succeeds.
    valid_failed = {
        "id": str(uuid.uuid4()),
        "ts": "2026-02-20T10:00:00Z",
        "type": "webhook_failed",
        "email": "replay@example.com",
        "detail": {
            "reason": "simulated downstream failure",
            "product": "base",
            "payload": {"email": "replay@example.com", "total_amount": "4700", "order_id": "po_valid_replay"},
            "source": "pinball",
        },
    }
    await db.activity.insert_one(valid_failed)
    r = await client.post(f"/api/admin/activity/{valid_failed['id']}/replay", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["status"] == "ok"
    doc = await db.buyers.find_one({"email": "replay@example.com"})
    assert "base" in doc["entitlements"]


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stats_shape(client):
    token = await _login(client, "admin@example.com")
    h = {"Authorization": f"Bearer {token}"}

    # Seed two buyers on different days
    await db.buyers.insert_many([
        {"email": "a@example.com", "entitlements": ["base"], "totalSpendCents": 1000, "addedAt": "2026-02-01T10:00:00Z"},
        {"email": "b@example.com", "entitlements": ["base", "studio"], "totalSpendCents": 5000, "addedAt": "2026-02-02T10:00:00Z"},
    ])

    r = await client.get("/api/admin/stats", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_users"] == 2
    assert body["revenue_cents"] == 6000
    # entitlement_breakdown structure
    assert set(body["entitlement_breakdown"].keys()) == {"base", "shorts", "studio"}
    assert body["entitlement_breakdown"]["base"] == 2
    assert body["entitlement_breakdown"]["studio"] == 1
    # signups_series sorted by date
    dates = [s["date"] for s in body["signups_series"]]
    assert dates == sorted(dates)
