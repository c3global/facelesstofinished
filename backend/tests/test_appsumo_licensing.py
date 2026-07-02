"""Pytest suite for the AppSumo Licensing v2 integration (appsumo_routes.py).

Scope: webhook token gate, HMAC verification, test-ping handling, the full
license lifecycle (purchase → redeem → activate → upgrade → deactivate),
refund clawback that preserves non-AppSumo entitlements, and the admin
license search. ZERO real API spend — the OAuth exchange is faked with a
stub httpx client and the DB is mongomock (no running mongod needed).

Run: `cd /app && pytest backend/tests/test_appsumo_licensing.py -v`
"""
import hashlib
import hmac
import importlib
import json
import os
import sys

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "/app/backend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["APPSUMO_WEBHOOK_TOKEN"] = "as_test-token-123"
os.environ["APPSUMO_API_KEY"] = ""  # HMAC off by default; enabled per-test via reload
os.environ["APPSUMO_CLIENT_ID"] = "cid"
os.environ["APPSUMO_CLIENT_SECRET"] = "csecret"
os.environ["APPSUMO_REDIRECT_URI"] = "https://faceless48.c3global.co/redeem"

import appsumo_routes  # noqa: E402

importlib.reload(appsumo_routes)

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

WEBHOOK = "/api/appsumo-webhook?token=as_test-token-123"

activity_log: list = []


class _StubUser:
    email = "admin@example.com"
    is_admin = True


async def _stub_current_user():
    return _StubUser()


async def _stub_log_activity(typ, email, detail):
    activity_log.append({"type": typ, "email": email, "detail": detail})


# ---------------------------------------------------------------------------
# Fake httpx.AsyncClient for the OAuth exchange (configured per-test)
# ---------------------------------------------------------------------------
FAKE_OAUTH = {
    "token_status": 200,
    "token_json": {"access_token": "tok123"},
    "license_status_code": 200,
    "license_json": {"license_key": "11111111-aaaa-bbbb-cccc-000000000001",
                     "status": "inactive", "scopes": ["read_license"]},
}


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, **kw):
        assert data["grant_type"] == "authorization_code"
        return _FakeResponse(FAKE_OAUTH["token_status"], FAKE_OAUTH["token_json"])

    async def get(self, url, params=None, **kw):
        assert params["access_token"] == "tok123"
        return _FakeResponse(FAKE_OAUTH["license_status_code"], FAKE_OAUTH["license_json"])


class _FakeHttpxModule:
    AsyncClient = _FakeAsyncClient

    @staticmethod
    def Timeout(*a, **kw):
        return None


@pytest_asyncio.fixture()
async def env():
    """Fresh app + mock db per test."""
    db = AsyncMongoMockClient()["f48_appsumo_test"]
    activity_log.clear()
    appsumo_routes.httpx = _FakeHttpxModule()
    FAKE_OAUTH.update(
        token_status=200,
        token_json={"access_token": "tok123"},
        license_status_code=200,
        license_json={"license_key": "11111111-aaaa-bbbb-cccc-000000000001",
                      "status": "inactive", "scopes": ["read_license"]},
    )
    api = FastAPI()
    appsumo_routes.register_appsumo_routes(
        api=api, db=db, current_user=_stub_current_user, log_activity=_stub_log_activity
    )
    app = FastAPI()
    app.mount("/api", api)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db


async def _post_webhook(client, body, url=WEBHOOK, headers=None):
    return await client.post(url, json=body, headers=headers or {})


# ---------------------------------------------------------------------------
# Gate + validation-ping tests
# ---------------------------------------------------------------------------
async def test_webhook_rejects_bad_token(env):
    client, db = env
    r = await _post_webhook(
        client,
        {"event": "purchase", "license_key": "k1"},
        url="/api/appsumo-webhook?token=WRONG",
    )
    assert r.status_code == 401
    assert await db.appsumo_licenses.count_documents({}) == 0


async def test_webhook_test_ping_returns_success_without_side_effects(env):
    client, db = env
    r = await _post_webhook(client, {
        "event": "purchase", "license_key": "00000000-aaaa-1111-bbbb-abcdef012345",
        "license_status": "inactive", "tier": 1, "test": True,
    })
    assert r.status_code == 200
    assert r.json() == {"event": "purchase", "success": True}
    assert await db.appsumo_licenses.count_documents({}) == 0
    assert await db.buyers.count_documents({}) == 0


async def test_webhook_hmac_signature_enforced_when_key_set(env):
    client, db = env
    appsumo_routes.APPSUMO_API_KEY = "secret-api-key"
    try:
        body = {"event": "purchase", "license_key": "k-hmac", "test": True}
        raw = json.dumps(body).encode()
        ts = "1751470000"
        good_sig = hmac.new(b"secret-api-key", ts.encode() + raw, hashlib.sha256).hexdigest()

        r = await client.post(
            WEBHOOK, content=raw,
            headers={"Content-Type": "application/json",
                     "X-Appsumo-Timestamp": ts, "X-Appsumo-Signature": "bogus"},
        )
        assert r.status_code == 401

        r = await client.post(
            WEBHOOK, content=raw,
            headers={"Content-Type": "application/json",
                     "X-Appsumo-Timestamp": ts, "X-Appsumo-Signature": good_sig},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
    finally:
        appsumo_routes.APPSUMO_API_KEY = ""


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------
LK1 = "11111111-aaaa-bbbb-cccc-000000000001"
LK2 = "22222222-aaaa-bbbb-cccc-000000000002"


async def test_purchase_creates_license_record(env):
    client, db = env
    r = await _post_webhook(client, {
        "event": "purchase", "license_key": LK1, "license_status": "inactive",
        "tier": 2, "event_timestamp": 1754671919169, "created_at": 1754671919158,
    })
    assert r.status_code == 200
    assert r.json() == {"event": "purchase", "success": True}
    lic = await db.appsumo_licenses.find_one({"license_key": LK1})
    assert lic["status"] == "purchased"
    assert lic["tier"] == 2


async def test_redeem_links_email_and_grants_tier_entitlements(env):
    client, db = env
    await _post_webhook(client, {"event": "purchase", "license_key": LK1, "tier": 2})

    r = await client.post("/api/appsumo/redeem",
                          json={"code": "abc123", "email": "Sumo@Example.com"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == "sumo@example.com"
    assert data["entitlements"] == ["base", "shorts"]  # tier 2

    buyer = await db.buyers.find_one({"email": "sumo@example.com"})
    assert buyer["entitlements"] == ["base", "shorts"]
    assert buyer["source"] == "appsumo"
    assert buyer["pending_welcome"] is True
    lic = await db.appsumo_licenses.find_one({"license_key": LK1})
    assert lic["email"] == "sumo@example.com"
    assert lic["granted_entitlements"] == ["base", "shorts"]


async def test_redeem_conflicting_email_is_rejected(env):
    client, db = env
    await _post_webhook(client, {"event": "purchase", "license_key": LK1, "tier": 1})
    r = await client.post("/api/appsumo/redeem", json={"code": "c1", "email": "first@x.com"})
    assert r.status_code == 200
    r = await client.post("/api/appsumo/redeem", json={"code": "c2", "email": "second@x.com"})
    assert r.status_code == 409


async def test_redeem_deactivated_license_is_rejected(env):
    client, db = env
    FAKE_OAUTH["license_json"] = {"license_key": LK1, "status": "deactivated"}
    r = await client.post("/api/appsumo/redeem", json={"code": "c1", "email": "x@x.com"})
    assert r.status_code == 410
    assert await db.buyers.count_documents({}) == 0


async def test_redeem_expired_code_maps_to_friendly_400(env):
    client, _db = env
    FAKE_OAUTH["token_status"] = 403
    FAKE_OAUTH["token_json"] = {"error": "invalid_grant"}
    r = await client.post("/api/appsumo/redeem", json={"code": "used", "email": "x@x.com"})
    assert r.status_code == 400
    assert "restart activation" in r.json()["detail"].lower()


async def test_upgrade_carries_email_and_deactivate_of_old_key_keeps_new_grants(env):
    client, db = env
    # Tier-1 purchase, redeemed.
    await _post_webhook(client, {"event": "purchase", "license_key": LK1, "tier": 1})
    await client.post("/api/appsumo/redeem", json={"code": "c1", "email": "up@x.com"})
    await _post_webhook(client, {"event": "activate", "license_key": LK1,
                                 "license_status": "inactive", "tier": 1})
    buyer = await db.buyers.find_one({"email": "up@x.com"})
    assert buyer["entitlements"] == ["base"]

    # Upgrade to tier 3 → new key LK2, then simultaneous deactivate of LK1.
    r = await _post_webhook(client, {
        "event": "upgrade", "license_key": LK2, "prev_license_key": LK1,
        "license_status": "inactive", "tier": 3,
    })
    assert r.json() == {"event": "upgrade", "success": True}
    r = await _post_webhook(client, {
        "event": "deactivate", "license_key": LK1, "license_status": "deactivated",
        "tier": 1, "extra": {"reason": "Upgraded by the customer"},
    })
    assert r.json() == {"event": "deactivate", "success": True}

    buyer = await db.buyers.find_one({"email": "up@x.com"})
    # tier-3 grants survive the old key's deactivation
    assert buyer["entitlements"] == ["base", "shorts", "studio"]
    new_lic = await db.appsumo_licenses.find_one({"license_key": LK2})
    assert new_lic["email"] == "up@x.com"
    assert new_lic["status"] == "active"
    old_lic = await db.appsumo_licenses.find_one({"license_key": LK1})
    assert old_lic["status"] == "deactivated"


async def test_refund_revokes_appsumo_grants_but_keeps_prior_purchases(env):
    client, db = env
    # Existing Pinball customer with base+shorts…
    await db.buyers.insert_one({
        "email": "loyal@x.com", "entitlements": ["base", "shorts"], "source": "webhook",
    })
    # …buys Studio-tier on AppSumo and redeems.
    await _post_webhook(client, {"event": "purchase", "license_key": LK1, "tier": 3})
    await client.post("/api/appsumo/redeem", json={"code": "c1", "email": "loyal@x.com"})
    buyer = await db.buyers.find_one({"email": "loyal@x.com"})
    assert buyer["entitlements"] == ["base", "shorts", "studio"]
    lic = await db.appsumo_licenses.find_one({"license_key": LK1})
    assert lic["granted_entitlements"] == ["studio"]  # only the NEW one

    # Refund → only the AppSumo-granted "studio" is clawed back.
    await _post_webhook(client, {"event": "deactivate", "license_key": LK1,
                                 "license_status": "active",
                                 "extra": {"reason": "Refunded by the user"}})
    buyer = await db.buyers.find_one({"email": "loyal@x.com"})
    assert buyer["entitlements"] == ["base", "shorts"]


async def test_migrate_updates_parent_license_key_only(env):
    client, db = env
    await _post_webhook(client, {
        "event": "purchase", "license_key": "addon-1", "tier": 1,
        "partner_plan_name": "add_on_user_seats", "unit_quantity": 5,
        "parent_license_key": LK1,
    })
    r = await _post_webhook(client, {
        "event": "migrate", "license_key": "addon-1", "tier": 1,
        "partner_plan_name": "add_on_user_seats", "unit_quantity": 5,
        "parent_license_key": LK2,
    })
    assert r.json() == {"event": "migrate", "success": True}
    addon = await db.appsumo_licenses.find_one({"license_key": "addon-1"})
    assert addon["parent_license_key"] == LK2


async def test_admin_license_search(env):
    client, db = env
    await _post_webhook(client, {"event": "purchase", "license_key": LK1, "tier": 1})
    await client.post("/api/appsumo/redeem", json={"code": "c1", "email": "findme@x.com"})
    r = await client.get("/api/admin/appsumo/licenses", params={"q": "findme"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["license_key"] == LK1
    r = await client.get("/api/admin/appsumo/licenses", params={"q": LK1[:8]})
    assert r.json()["total"] == 1
