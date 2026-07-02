"""End-to-end pytest suite for the AppSumo launch path (2026-07-02 fixes).

Covers the four launch-blocking gaps found after merging Emergent's branch:
  1. AppSumo webhooks send NUMERIC tiers (1/2/3) — mapped to t1/t3/t4.
  2. Redemption never granted entitlements → buyers couldn't sign back in.
  3. AppSumo license keys / OAuth codes had no redemption path (only the
     pre-uploaded partner-code inventory worked).
  4. New AppSumo buyers couldn't sign in at all (magic-link verify requires
     an existing buyer, redemption requires sign-in) — fixed by letting the
     code ride along with the magic-link token and redeeming after verify.
Plus: Sprint Mode tier gate (T1 blocked per listing) and the tier quota
values from the final listing copy.

ZERO real API spend / no mongod: motor is swapped for mongomock before
server import, and the AppSumo OAuth exchange is stubbed.

Run: `cd /app && pytest backend/tests/test_appsumo_launch_flow.py -v`
"""
import os
import sys

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "/app/backend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "f48_launch_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DEV_BYPASS_EMAIL", "")
os.environ.setdefault("STUDIO_GRANT_EMAILS", "")

# Swap motor for mongomock BEFORE server import so every register_* closure
# captures the mock db. GridFS (uploads_routes) can't run on mongomock, so
# it's stubbed — no test here touches file uploads.
from mongomock_motor import AsyncMongoMockClient  # noqa: E402
import motor.motor_asyncio as _motor  # noqa: E402

_motor.AsyncIOMotorClient = lambda *a, **kw: AsyncMongoMockClient()


class _StubGridFS:
    def __init__(self, *a, **kw):
        pass

    def __getattr__(self, name):
        raise RuntimeError("GridFS is not available in this test suite")


_motor.AsyncIOMotorGridFSBucket = _StubGridFS

import uploads_routes  # noqa: E402

uploads_routes.AsyncIOMotorGridFSBucket = _StubGridFS

import licenses_routes  # noqa: E402
import server  # noqa: E402
import tier_config  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    for coll in ("buyers", "appsumo_licenses", "redemption_codes",
                 "magic_link_tokens", "activity", "settings", "scripts"):
        await server.db[coll].delete_many({})
    yield


@pytest_asyncio.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=server.app),
                           base_url="http://test") as c:
        yield c


def _auth(email, ents=("base", "shorts", "studio")):
    token = server.issue_jwt(email, list(ents))
    return {"Authorization": f"Bearer {token}"}


LK = "d8bfa201-d8c0-4bc8-a27c-b1c12efa4a5a"


# ---------------------------------------------------------------------------
# Tier mapping + config
# ---------------------------------------------------------------------------
def test_numeric_tier_mapping_matches_listing():
    assert tier_config.appsumo_tier_to_tier_id(1) == "t1"
    assert tier_config.appsumo_tier_to_tier_id("2") == "t3"
    assert tier_config.appsumo_tier_to_tier_id(3.0) == "t4"
    assert tier_config.appsumo_tier_to_tier_id("t2") == "t2"   # internal passthrough
    assert tier_config.appsumo_tier_to_tier_id("founder") == ""  # never external
    assert tier_config.appsumo_tier_to_tier_id("bogus") == ""


def test_tier_values_match_final_listing():
    t1, t3, t4 = tier_config.TIER_T1, tier_config.TIER_T3, tier_config.TIER_T4
    assert "shorts" in t1.entitlements          # Shorts Engine in ALL plans
    assert t1.render_quota_monthly == 0         # T1: no Faceless videos
    assert t1.sprint_allowed is False           # T1: no Sprint Mode
    assert t1.thumbnail_quota_monthly == 20
    assert (t3.render_quota_monthly, t3.avatar_sub_cap) == (3, 0)
    assert t3.thumbnail_quota_monthly == 50
    assert (t4.render_quota_monthly, t4.avatar_sub_cap) == (13, 3)
    assert t4.thumbnail_quota_monthly == 100
    assert t4.byok_allowed is True


def test_assign_buyer_to_tier_stamps_entitlements():
    payload = tier_config.assign_buyer_to_tier(tier_id="t3")
    assert payload["entitlements"] == ["base", "shorts", "studio"]
    assert payload["tier"] == "t3"


# ---------------------------------------------------------------------------
# Webhook: numeric tiers end-to-end
# ---------------------------------------------------------------------------
async def test_webhook_purchase_stores_license_and_test_ping_acks(client):
    r = await client.post("/api/appsumo-webhook", json={
        "event": "purchase", "license_key": LK, "license_status": "inactive",
        "tier": 2, "event_timestamp": 1754671919169,
    })
    assert r.status_code == 200
    assert r.json()["success"] is True
    lic = await server.db.appsumo_licenses.find_one({"license_key": LK})
    assert lic is not None and lic["tier"] == 2

    r = await client.post("/api/appsumo-webhook", json={
        "event": "activate", "license_key": "00000000-aaaa-1111-bbbb-abcdef012345",
        "tier": 1, "test": True,
    })
    assert r.status_code == 200
    assert r.json() == {"event": "activate", "success": True}


async def test_webhook_upgrade_with_numeric_tier_bumps_buyer(client):
    # Buyer already linked to the license (post-redemption state).
    await server.db.appsumo_licenses.insert_one(
        {"license_key": LK, "tier": 2, "email": "up@x.com"})
    await server.db.buyers.insert_one({
        "email": "up@x.com", "tier": "t3",
        "entitlements": ["base", "shorts", "studio"], "founders": False,
    })
    r = await client.post("/api/appsumo-webhook", json={
        "event": "upgrade", "license_key": "new-key-123",
        "prev_license_key": LK, "tier": 3,   # numeric, as AppSumo sends it
        "event_timestamp": 1754671920000,
    })
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    buyer = await server.db.buyers.find_one({"email": "up@x.com"})
    assert buyer["tier"] == "t4"
    assert buyer["entitlements"] == ["base", "byok", "shorts", "studio"]


# ---------------------------------------------------------------------------
# Redemption: AppSumo license key + OAuth paths
# ---------------------------------------------------------------------------
async def test_redeem_endpoint_accepts_appsumo_license_key(client):
    await server.db.appsumo_licenses.insert_one({"license_key": LK, "tier": 2})
    r = await client.post("/api/licenses/redeem", json={"code": LK},
                          headers=_auth("sumo@x.com", ents=["base"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tier"] == "t3"
    buyer = await server.db.buyers.find_one({"email": "sumo@x.com"})
    assert buyer["tier"] == "t3"
    assert buyer["entitlements"] == ["base", "shorts", "studio"]
    lic = await server.db.appsumo_licenses.find_one({"license_key": LK})
    assert lic["email"] == "sumo@x.com"


async def test_redeem_license_key_conflicts_and_deactivation(client):
    await server.db.appsumo_licenses.insert_one(
        {"license_key": LK, "tier": 1, "email": "owner@x.com"})
    r = await client.post("/api/licenses/redeem", json={"code": LK},
                          headers=_auth("thief@x.com", ents=["base"]))
    assert r.status_code == 409

    await server.db.appsumo_licenses.insert_one(
        {"license_key": "22222222-2222-2222-2222-222222222222",
         "tier": 1, "last_event": "deactivate"})
    r = await client.post("/api/licenses/redeem",
                          json={"code": "22222222-2222-2222-2222-222222222222"},
                          headers=_auth("x@x.com", ents=["base"]))
    assert r.status_code == 410


async def test_redeem_unknown_code_still_404s(client):
    r = await client.post("/api/licenses/redeem",
                          json={"code": "NOPE-NOPE-NOPE"},
                          headers=_auth("x@x.com", ents=["base"]))
    assert r.status_code == 404


async def test_inventory_code_path_regression(client):
    await server.db.redemption_codes.insert_one({
        "_id": "PARTNER-CODE-123", "tier": "t4", "status": "available",
        "source": "partner",
    })
    r = await client.post("/api/licenses/redeem", json={"code": "partner-code-123"},
                          headers=_auth("p@x.com", ents=["base"]))
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "t4"
    buyer = await server.db.buyers.find_one({"email": "p@x.com"})
    assert buyer["entitlements"] == ["base", "byok", "shorts", "studio"]
    code = await server.db.redemption_codes.find_one({"_id": "PARTNER-CODE-123"})
    assert code["status"] == "redeemed" and code["redeemed_by"] == "p@x.com"


async def test_redeem_oauth_endpoint(client, monkeypatch):
    async def _fake_exchange(db, oauth_code):
        assert oauth_code == "1d512d96ba99465ba9942bdf282233ea"
        return {"license_key": LK, "status": "inactive"}

    monkeypatch.setattr(licenses_routes, "exchange_appsumo_oauth_code", _fake_exchange)
    await server.db.appsumo_licenses.insert_one({"license_key": LK, "tier": 3})
    r = await client.post("/api/licenses/redeem-oauth",
                          json={"code": "1d512d96ba99465ba9942bdf282233ea"},
                          headers=_auth("oauth@x.com", ents=["base"]))
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "t4"


# ---------------------------------------------------------------------------
# New-buyer onboarding: code rides the magic link
# ---------------------------------------------------------------------------
async def test_magic_link_carries_code_and_provisions_new_buyer(client):
    await server.db.appsumo_licenses.insert_one({"license_key": LK, "tier": 2})

    # New buyer requests a sign-in link WITH their license key attached.
    r = await client.post("/api/auth/request-magic-link",
                          json={"email": "new@x.com", "redeem": LK})
    assert r.status_code == 200 and r.json()["ok"] is True
    tok = await server.db.magic_link_tokens.find_one({"email": "new@x.com"})
    assert tok and tok["redeem_code"] == LK

    # Clicking the emailed link proves the email → redemption runs →
    # buyer exists with entitlements → JWT issued via callback redirect.
    r = await client.get(f"/api/auth/verify-magic-link?token={tok['token']}")
    assert r.status_code == 302
    assert "/auth/callback#jwt=" in r.headers["location"]
    buyer = await server.db.buyers.find_one({"email": "new@x.com"})
    assert buyer["tier"] == "t3"
    assert buyer["entitlements"] == ["base", "shorts", "studio"]


async def test_magic_link_with_bad_code_and_no_access_shows_code_error(client):
    r = await client.post("/api/auth/request-magic-link",
                          json={"email": "stranger@x.com", "redeem": "BAD-CODE-999"})
    assert r.status_code == 200
    tok = await server.db.magic_link_tokens.find_one({"email": "stranger@x.com"})
    r = await client.get(f"/api/auth/verify-magic-link?token={tok['token']}")
    assert r.status_code == 302
    assert "err=code_invalid" in r.headers["location"]


async def test_magic_link_oauth_code_rides_with_prefix(client, monkeypatch):
    async def _fake_exchange(db, oauth_code):
        return {"license_key": LK, "status": "inactive"}

    monkeypatch.setattr(licenses_routes, "exchange_appsumo_oauth_code", _fake_exchange)
    await server.db.appsumo_licenses.insert_one({"license_key": LK, "tier": 3})

    r = await client.post("/api/auth/request-magic-link",
                          json={"email": "oauthnew@x.com",
                                "appsumo_oauth": "abc123DEF"})
    assert r.status_code == 200
    tok = await server.db.magic_link_tokens.find_one({"email": "oauthnew@x.com"})
    assert tok["redeem_code"] == "oauth:abc123DEF"

    r = await client.get(f"/api/auth/verify-magic-link?token={tok['token']}")
    assert r.status_code == 302
    assert "/auth/callback#jwt=" in r.headers["location"]
    buyer = await server.db.buyers.find_one({"email": "oauthnew@x.com"})
    assert buyer["tier"] == "t4"


# ---------------------------------------------------------------------------
# Sprint Mode tier gate
# ---------------------------------------------------------------------------
async def test_sprint_blocked_for_t1_allowed_for_t3_and_legacy(client, monkeypatch):
    async def _stub_enqueue(**kwargs):
        return {"id": "stub", "status": "queued", "mode": kwargs.get("mode")}

    monkeypatch.setattr(server, "_enqueue_script", _stub_enqueue)
    await server.db.buyers.insert_one({
        "email": "t1@x.com", "tier": "t1",
        "entitlements": ["base", "shorts"], "founders": False,
    })
    await server.db.buyers.insert_one({
        "email": "t3@x.com", "tier": "t3",
        "entitlements": ["base", "shorts", "studio"], "founders": False,
    })
    await server.db.buyers.insert_one({
        "email": "legacy@x.com",           # pre-tier buyer — never gated
        "entitlements": ["base", "shorts"],
    })
    body = {"topic": "test", "platform": "youtube", "sprint": True}

    r = await client.post("/api/scripts/shorts", json=body,
                          headers=_auth("t1@x.com", ents=["base", "shorts"]))
    assert r.status_code == 403
    assert "Sprint" in r.json()["detail"]

    r = await client.post("/api/scripts/shorts", json=body,
                          headers=_auth("t3@x.com"))
    assert r.status_code == 200

    r = await client.post("/api/scripts/shorts", json=body,
                          headers=_auth("legacy@x.com", ents=["base", "shorts"]))
    assert r.status_code == 200

    # Plain (non-sprint) shorts stay available at T1.
    r = await client.post("/api/scripts/shorts",
                          json={"topic": "t", "platform": "youtube"},
                          headers=_auth("t1@x.com", ents=["base", "shorts"]))
    assert r.status_code == 200
