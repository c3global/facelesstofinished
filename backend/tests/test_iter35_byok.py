"""
Iter 35 — Group E (BYOK / Bring Your Own Key) tests:
- GET /api/user/byok: 401 without JWT; full service list with byok_allowed=true
  for owner (DEV_BYPASS); byok_allowed=false for non-Pro-Plus buyer.
- POST /api/user/byok: success path persists encrypted; short key 400;
  unknown service 400; non-Pro-Plus 403 reason=byok_not_allowed.
- DELETE /api/user/byok/{service}: 200 removes; non-existent 404.
- Idempotent upsert (created_at preserved, updated_at bumped).
- Encryption sanity (ciphertext != plaintext in db.byok_keys).
- BYOK helper integration in render code paths (static source verification).
"""

import os
import re
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "f48_studio")
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

OWNER_EMAIL = "drcharitycampbell@gmail.com"
JWT_SECRET = "2a8f1ec39cd5b67a9e1d04ee2c7c3b6d4f0e2a9b8c5d7e3f1a6c9b4d8e2f0a7c"


# ---------- Auth helpers ----------
def _owner_auth() -> dict:
    r = requests.post(f"{API}/auth/check", json={"email": OWNER_EMAIL}, timeout=10)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _forge_jwt(email: str, entitlements=None, is_admin=False) -> dict:
    import jwt as _jwt
    token = _jwt.encode(
        {"email": email, "entitlements": entitlements or ["base"], "isAdmin": is_admin},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_buyer(email: str, tier: str = "t1", founders: bool = False):
    db.buyers.update_one(
        {"email": email},
        {"$set": {
            "email": email, "tier": tier, "founders": founders,
            "entitlements": ["base"], "rendersThisCycle": 0, "renderQuotaMonthly": 5,
        }},
        upsert=True,
    )


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner_h():
    return _owner_auth()


@pytest.fixture(scope="module")
def t1_buyer():
    email = f"test_iter35_byok_t1_{uuid.uuid4().hex[:8]}@example.com"
    _seed_buyer(email, tier="t1")
    yield email
    db.buyers.delete_one({"email": email})
    db.byok_keys.delete_many({"email": email})


@pytest.fixture(scope="module")
def t4_buyer():
    email = f"test_iter35_byok_t4_{uuid.uuid4().hex[:8]}@example.com"
    _seed_buyer(email, tier="t4")
    yield email
    db.buyers.delete_one({"email": email})
    db.byok_keys.delete_many({"email": email})


@pytest.fixture(autouse=True)
def _cleanup_owner_keys():
    """Wipe owner's BYOK keys before each test so save/list/delete tests
    have a clean baseline. Other test buyers are cleaned per-fixture."""
    db.byok_keys.delete_many({"email": OWNER_EMAIL})
    yield
    db.byok_keys.delete_many({"email": OWNER_EMAIL})


# ---------- 1. Auth gating + list ----------
def test_get_byok_requires_jwt():
    r = requests.get(f"{API}/user/byok", timeout=10)
    assert r.status_code in (401, 403), r.text


def test_get_byok_owner_allowed(owner_h):
    r = requests.get(f"{API}/user/byok", headers=owner_h, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("byok_allowed") is True, data
    svcs = data.get("services") or []
    ids = sorted([s["id"] for s in svcs])
    assert ids == ["fal", "heygen", "openai"], ids
    for s in svcs:
        assert s.get("configured") is False, s
        assert "label" in s and "purpose" in s and "key_hint" in s


def test_get_byok_t1_buyer_denied(t1_buyer):
    h = _forge_jwt(t1_buyer)
    r = requests.get(f"{API}/user/byok", headers=h, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("byok_allowed") is False, data


def test_get_byok_t4_buyer_allowed(t4_buyer):
    h = _forge_jwt(t4_buyer)
    r = requests.get(f"{API}/user/byok", headers=h, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("byok_allowed") is True, r.json()


# ---------- 2. Save key flow ----------
def test_post_byok_save_success_and_masked(owner_h):
    full = "sk-test-byok-1234567890abc"
    r = requests.post(
        f"{API}/user/byok",
        headers=owner_h,
        json={"service": "openai", "key": full},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("service") == "openai"
    hint = body.get("hint", "")
    # Must NOT contain the full plaintext key
    assert full not in hint, hint
    # Mask format: first3…last4
    assert hint.startswith("sk-") and hint.endswith(full[-4:]), hint
    assert "…" in hint, hint

    # GET should reflect configured:true with same hint
    g = requests.get(f"{API}/user/byok", headers=owner_h, timeout=10).json()
    openai_card = next(s for s in g["services"] if s["id"] == "openai")
    assert openai_card["configured"] is True
    assert openai_card["hint"] == hint
    assert full not in str(g)  # plaintext NEVER returned anywhere


def test_post_byok_short_key_400(owner_h):
    r = requests.post(
        f"{API}/user/byok",
        headers=owner_h,
        json={"service": "openai", "key": "short"},
        timeout=10,
    )
    # Pydantic min_length=8 -> 422; or app-level guard -> 400. Both acceptable.
    assert r.status_code in (400, 422), r.text


def test_post_byok_unknown_service_400(owner_h):
    r = requests.post(
        f"{API}/user/byok",
        headers=owner_h,
        json={"service": "bogus_svc", "key": "longenoughkey123"},
        timeout=10,
    )
    assert r.status_code == 400, r.text


def test_post_byok_t1_buyer_forbidden(t1_buyer):
    h = _forge_jwt(t1_buyer)
    r = requests.post(
        f"{API}/user/byok",
        headers=h,
        json={"service": "openai", "key": "sk-good-enough-1234"},
        timeout=10,
    )
    assert r.status_code == 403, r.text
    detail = r.json().get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("reason") == "byok_not_allowed", detail


# ---------- 3. Delete flow ----------
def test_delete_byok_success_and_removes_from_db(owner_h):
    # Save first
    requests.post(
        f"{API}/user/byok",
        headers=owner_h,
        json={"service": "heygen", "key": "hg-key-abcdefgh-test"},
        timeout=10,
    )
    assert db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "heygen"}) is not None

    r = requests.delete(f"{API}/user/byok/heygen", headers=owner_h, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True
    assert db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "heygen"}) is None


def test_delete_byok_nonexistent_404(owner_h):
    r = requests.delete(f"{API}/user/byok/fal", headers=owner_h, timeout=10)
    assert r.status_code == 404, r.text


# ---------- 4. Idempotent upsert ----------
def test_save_twice_replaces_and_preserves_created_at(owner_h):
    full1 = "sk-first-key-aaaaaaaaa"
    full2 = "sk-second-key-bbbbbbbbb"
    r1 = requests.post(f"{API}/user/byok", headers=owner_h,
                       json={"service": "openai", "key": full1}, timeout=10)
    assert r1.status_code == 200
    doc1 = db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "openai"})
    assert doc1 is not None
    enc1 = doc1["encrypted_key"]
    created1 = doc1["created_at"]

    time.sleep(1.05)  # ensure timestamp bumps

    r2 = requests.post(f"{API}/user/byok", headers=owner_h,
                       json={"service": "openai", "key": full2}, timeout=10)
    assert r2.status_code == 200
    doc2 = db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "openai"})
    # encrypted_key changed
    assert doc2["encrypted_key"] != enc1, "encrypted_key should change on replace"
    # created_at preserved
    assert doc2["created_at"] == created1, "created_at must be preserved"
    # updated_at bumped (>= created_at)
    assert doc2.get("updated_at") and doc2["updated_at"] >= created1


# ---------- 5. Encryption sanity at rest ----------
def test_encryption_sanity_in_mongo(owner_h):
    full = "sk-secretly-stored-plaintext-1234"
    r = requests.post(f"{API}/user/byok", headers=owner_h,
                      json={"service": "fal", "key": full}, timeout=10)
    assert r.status_code == 200
    doc = db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "fal"})
    assert doc is not None
    enc = doc["encrypted_key"]
    # Plaintext must NOT appear in the encrypted blob
    assert full not in enc, "ciphertext should not contain plaintext"
    # Fernet tokens start with 'gAAAAA' (version byte)
    assert enc.startswith("gAAAAA"), enc[:10]


# ---------- 6. BYOK wired into render pipelines (static source check) ----------
def test_byok_wired_in_render_avatar_and_faceless():
    with open("/app/backend/server.py") as fh:
        src = fh.read()
    # Avatar render path
    assert "get_byok_key(db, user_email, \"heygen\")" in src, "heygen BYOK lookup missing"
    assert "_override_heygen_key_ctx.set(user_heygen)" in src
    # Faceless render path
    assert "get_byok_key(db, user_email, \"fal\")" in src, "fal BYOK lookup missing"
    assert "_override_fal_key_ctx.set(user_fal)" in src
    # Nested helpers consume effective key
    assert src.count("_effective_fal_key()") >= 3, "fal effective key not used in helpers"
    assert "_effective_heygen_key()" in src
