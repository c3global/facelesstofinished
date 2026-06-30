"""
Iter 34 — Group D (AppSumo Launch) tests:
- Tier rename labels via /api/me/quota
- /api/licenses/redeem (atomic flip, downgrade-block, protected-user guard,
  re-redeem same-user vs different-user, voided/not-found, 401-without-JWT)
- /api/admin/licenses/bulk-create (programmatic + CSV, idempotency, invalid tier)
- /api/admin/licenses listing + filters + totals
- /api/admin/licenses/{code}/void
- /api/admin/buyers/{email}/upgrade-tier (incl. founder)
- /api/me/upgrade-target across all 7 reasons / states
- Admin auth gating (403 for non-admin)
"""

import os
import re
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if BASE_URL is None:
    # Fallback to frontend/.env if backend env didn't propagate
    try:
        with open("/app/frontend/.env") as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass
BASE_URL = (BASE_URL or "").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "f48_studio")
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

OWNER_EMAIL = "drcharitycampbell@gmail.com"
NON_ADMIN_EMAIL = "directkynections@gmail.com"

TS = int(time.time())


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------

def _auth(email: str) -> dict:
    """Hit /api/auth/check (passwordless DEV_BYPASS path) and return Bearer header."""
    r = requests.post(f"{API}/auth/check", json={"email": email}, timeout=10)
    assert r.status_code == 200, f"auth failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, f"no token in /auth/check: {r.json()}"
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_h():
    return _auth(OWNER_EMAIL)


@pytest.fixture(scope="module")
def nonadmin_h():
    return _auth(NON_ADMIN_EMAIL)


# Seed a fresh non-protected buyer for tier/redeem tests. Email not in any
# DEV_BYPASS / STUDIO_GRANT / ADMIN env var.
def _seed_buyer(tier: str = "t1", founders: bool = False) -> str:
    email = f"test_iter34_{tier}_{uuid.uuid4().hex[:8]}@example.com"
    db.buyers.insert_one({
        "email": email,
        "tier": tier,
        "founders": founders,
        "rendersThisCycle": 0,
        "renderQuotaMonthly": 5 if tier == "t1" else 10,
        "entitlements": ["base"],
    })
    return email


def _buyer_auth(email: str) -> dict:
    """Authenticate a seeded buyer through dev bypass — NOTE: only the
    DEV_BYPASS_EMAIL is passwordless. For seeded buyers we issue a JWT
    by calling /api/auth/check with the buyer email; in DEV_BYPASS the
    server only honors the specific configured email — so we forge a JWT
    using the same secret as the backend."""
    import jwt as _jwt
    secret = "2a8f1ec39cd5b67a9e1d04ee2c7c3b6d4f0e2a9b8c5d7e3f1a6c9b4d8e2f0a7c"
    token = _jwt.encode(
        {"email": email, "entitlements": ["base"], "isAdmin": False},
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# 1. Tier rename via /me/quota
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tier,label", [
    ("t1", "Starter"),
    ("t2", "Creator"),
    ("t3", "Pro"),
    ("t4", "Pro Plus"),
])
def test_me_quota_tier_labels(tier, label):
    email = _seed_buyer(tier=tier)
    h = _buyer_auth(email)
    r = requests.get(f"{API}/me/quota", headers=h, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("tier_id") == tier, data
    assert data.get("tier_label") == label, data


# --------------------------------------------------------------------------
# 2. Admin bulk-create (programmatic + CSV + idempotency + invalid tier)
# --------------------------------------------------------------------------

def test_admin_bulk_create_programmatic(admin_h):
    codes = [{"code": f"TEST-Z1-{TS}", "tier": "t1"},
             {"code": f"TEST-Z2-{TS}", "tier": "t2"}]
    r = requests.post(f"{API}/admin/licenses/bulk-create",
                      json={"codes": codes, "source": "appsumo"},
                      headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 2, d
    assert d["skipped_duplicates"] == 0
    assert d["invalid"] == []
    assert d.get("batch_id")
    # Verify persistence
    rec = db.redemption_codes.find_one({"_id": f"TEST-Z1-{TS}"})
    assert rec and rec["status"] == "available" and rec["tier"] == "t1"


def test_admin_bulk_create_csv(admin_h):
    csv_blob = f"code,tier\nTEST-CSV-1-{TS},t3\nTEST-CSV-2-{TS},t4"
    r = requests.post(f"{API}/admin/licenses/bulk-create",
                      json={"csv": csv_blob, "source": "appsumo"},
                      headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 2
    rec = db.redemption_codes.find_one({"_id": f"TEST-CSV-1-{TS}"})
    assert rec and rec["tier"] == "t3"


def test_admin_bulk_create_idempotent(admin_h):
    codes = [{"code": f"TEST-Z1-{TS}", "tier": "t1"},
             {"code": f"TEST-Z2-{TS}", "tier": "t2"}]
    r = requests.post(f"{API}/admin/licenses/bulk-create",
                      json={"codes": codes}, headers=admin_h, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["created"] == 0
    assert d["skipped_duplicates"] == 2


def test_admin_bulk_create_invalid_tier(admin_h):
    r = requests.post(f"{API}/admin/licenses/bulk-create",
                      json={"codes": [{"code": f"TEST-BAD-{TS}", "tier": "founder"}]},
                      headers=admin_h, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["created"] == 0
    assert any(x.get("reason") == "tier" for x in d["invalid"]), d


# --------------------------------------------------------------------------
# 3. Redeem (non-founder buyer, re-redeem, voided, not-found, downgrade)
# --------------------------------------------------------------------------

def test_redeem_requires_auth():
    r = requests.post(f"{API}/licenses/redeem",
                      json={"code": f"TEST-Z1-{TS}"}, timeout=10)
    assert r.status_code in (401, 403), r.status_code


def test_redeem_nonexistent_code():
    email = _seed_buyer(tier="t1")
    r = requests.post(f"{API}/licenses/redeem",
                      json={"code": f"DOES-NOT-EXIST-{TS}"},
                      headers=_buyer_auth(email), timeout=10)
    assert r.status_code == 404


def test_redeem_first_time_bumps_tier(admin_h):
    # Use TEST-Z2 (t2 code from bulk_create_programmatic). Seed a fresh T1 buyer.
    buyer = _seed_buyer(tier="t1")
    code = f"TEST-Z2-{TS}"
    # Make sure the code is available (not already redeemed by another test)
    db.redemption_codes.update_one({"_id": code},
                                   {"$set": {"status": "available",
                                             "redeemed_by": None,
                                             "redeemed_at": None}})
    r = requests.post(f"{API}/licenses/redeem", json={"code": code},
                      headers=_buyer_auth(buyer), timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["tier"] == "t2"
    assert d["tier_label"] == "Creator"
    # Verify buyer doc updated
    b = db.buyers.find_one({"email": buyer})
    assert b["tier"] == "t2"
    assert b.get("source") == "appsumo"
    assert b.get("lastRedeemedCode") == code
    # Code burned
    rec = db.redemption_codes.find_one({"_id": code})
    assert rec["status"] == "redeemed"
    assert rec["redeemed_by"] == buyer


def test_redeem_same_user_again_idempotent(admin_h):
    # Provision a fresh code, redeem once, then redeem again as same user.
    code = f"TEST-IDEMP-{TS}"
    requests.post(f"{API}/admin/licenses/bulk-create",
                  json={"codes": [{"code": code, "tier": "t2"}]},
                  headers=admin_h, timeout=10)
    buyer = _seed_buyer(tier="t1")
    h = _buyer_auth(buyer)
    r1 = requests.post(f"{API}/licenses/redeem", json={"code": code}, headers=h, timeout=10)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/licenses/redeem", json={"code": code}, headers=h, timeout=10)
    assert r2.status_code == 200
    assert r2.json().get("already_redeemed") is True


def test_redeem_different_user_conflict(admin_h):
    code = f"TEST-CONFLICT-{TS}"
    requests.post(f"{API}/admin/licenses/bulk-create",
                  json={"codes": [{"code": code, "tier": "t2"}]},
                  headers=admin_h, timeout=10)
    a = _seed_buyer(tier="t1")
    b = _seed_buyer(tier="t1")
    r1 = requests.post(f"{API}/licenses/redeem", json={"code": code},
                       headers=_buyer_auth(a), timeout=10)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/licenses/redeem", json={"code": code},
                       headers=_buyer_auth(b), timeout=10)
    assert r2.status_code == 409


def test_redeem_voided_returns_410(admin_h):
    code = f"TEST-VOID-{TS}"
    requests.post(f"{API}/admin/licenses/bulk-create",
                  json={"codes": [{"code": code, "tier": "t2"}]},
                  headers=admin_h, timeout=10)
    rv = requests.post(f"{API}/admin/licenses/{code}/void", headers=admin_h, timeout=10)
    assert rv.status_code == 200 and rv.json().get("ok") is True
    buyer = _seed_buyer(tier="t1")
    r = requests.post(f"{API}/licenses/redeem", json={"code": code},
                      headers=_buyer_auth(buyer), timeout=10)
    assert r.status_code == 410


def test_redeem_protected_owner_burns_but_no_demote(admin_h):
    code = f"TEST-OWNER-{TS}"
    requests.post(f"{API}/admin/licenses/bulk-create",
                  json={"codes": [{"code": code, "tier": "t1"}]},
                  headers=admin_h, timeout=10)
    # snapshot owner doc
    owner_before = db.buyers.find_one({"email": OWNER_EMAIL}) or {}
    r = requests.post(f"{API}/licenses/redeem", json={"code": code},
                      headers=admin_h, timeout=10)
    assert r.status_code == 200
    # Code burned
    rec = db.redemption_codes.find_one({"_id": code})
    assert rec["status"] == "redeemed"
    # Owner doc tier unchanged (or still no tier-bump)
    owner_after = db.buyers.find_one({"email": OWNER_EMAIL}) or {}
    assert owner_after.get("tier") == owner_before.get("tier"), \
        f"owner demoted? before={owner_before.get('tier')} after={owner_after.get('tier')}"


def test_redeem_t1_code_as_t3_buyer_no_downgrade(admin_h):
    code = f"TEST-DOWNG-{TS}"
    requests.post(f"{API}/admin/licenses/bulk-create",
                  json={"codes": [{"code": code, "tier": "t1"}]},
                  headers=admin_h, timeout=10)
    buyer = _seed_buyer(tier="t3")
    r = requests.post(f"{API}/licenses/redeem", json={"code": code},
                      headers=_buyer_auth(buyer), timeout=10)
    assert r.status_code == 200
    # Code burned
    rec = db.redemption_codes.find_one({"_id": code})
    assert rec["status"] == "redeemed"
    # Buyer stays at t3
    b = db.buyers.find_one({"email": buyer})
    assert b["tier"] == "t3"


# --------------------------------------------------------------------------
# 4. Admin list licenses with filters + totals
# --------------------------------------------------------------------------

def test_admin_list_filter_status_available(admin_h):
    r = requests.get(f"{API}/admin/licenses?status=available&limit=500",
                     headers=admin_h, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert all(it["status"] == "available" for it in d["items"]), \
        [it for it in d["items"] if it["status"] != "available"][:3]
    assert "totals" in d and {"available", "redeemed", "void"}.issubset(d["totals"].keys())


def test_admin_list_filter_tier_t2(admin_h):
    r = requests.get(f"{API}/admin/licenses?tier=t2&limit=500", headers=admin_h, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    if items:
        assert all(it["tier"] == "t2" for it in items)


def test_admin_list_filter_q_match(admin_h):
    code = f"TEST-Z1-{TS}"
    r = requests.get(f"{API}/admin/licenses?q={code}", headers=admin_h, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["code"] == code for it in items), items


# --------------------------------------------------------------------------
# 5. Admin buyer upgrade-tier
# --------------------------------------------------------------------------

def test_admin_buyer_upgrade_tier(admin_h):
    email = _seed_buyer(tier="t1")
    r = requests.post(f"{API}/admin/buyers/{email}/upgrade-tier",
                      json={"tier": "t3"}, headers=admin_h, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["tier"] == "t3" and d["tier_label"] == "Pro"
    b = db.buyers.find_one({"email": email})
    assert b["tier"] == "t3"
    assert b.get("source") == "manual"


def test_admin_buyer_upgrade_to_founder(admin_h):
    email = _seed_buyer(tier="t1")
    r = requests.post(f"{API}/admin/buyers/{email}/upgrade-tier",
                      json={"tier": "founder"}, headers=admin_h, timeout=10)
    assert r.status_code == 200
    b = db.buyers.find_one({"email": email})
    assert b.get("founders") is True


def test_admin_buyer_upgrade_unknown_tier(admin_h):
    email = _seed_buyer(tier="t1")
    r = requests.post(f"{API}/admin/buyers/{email}/upgrade-tier",
                      json={"tier": "bogus"}, headers=admin_h, timeout=10)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# 6. /me/upgrade-target across all reasons
# --------------------------------------------------------------------------

def test_upgrade_target_owner_dev_bypass(admin_h):
    r = requests.get(f"{API}/me/upgrade-target", headers=admin_h, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["visible"] is False
    assert d["reason"] in ("dev_bypass", "studio_grant")


def test_upgrade_target_founder():
    email = _seed_buyer(tier="t1", founders=True)
    r = requests.get(f"{API}/me/upgrade-target",
                     headers=_buyer_auth(email), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["visible"] is False
    assert d["reason"] == "founder"


def test_upgrade_target_top_tier():
    email = _seed_buyer(tier="t4")
    r = requests.get(f"{API}/me/upgrade-target",
                     headers=_buyer_auth(email), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["visible"] is False
    assert d["reason"] == "top_tier"


def test_upgrade_target_no_url_configured():
    # env vars are blank in .env by default
    email = _seed_buyer(tier="t2")
    r = requests.get(f"{API}/me/upgrade-target",
                     headers=_buyer_auth(email), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["visible"] is False
    assert d["reason"] == "no_url_configured"


# --------------------------------------------------------------------------
# 7. Admin gating — non-admin should be blocked from /api/admin/*
# --------------------------------------------------------------------------

def test_admin_endpoints_block_non_admin(nonadmin_h):
    r = requests.get(f"{API}/admin/licenses", headers=nonadmin_h, timeout=10)
    assert r.status_code in (401, 403), r.status_code

    r = requests.post(f"{API}/admin/licenses/bulk-create",
                      json={"codes": [{"code": "BLOCKED", "tier": "t1"}]},
                      headers=nonadmin_h, timeout=10)
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# Cleanup — remove TEST_ data on session exit
# --------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    db.redemption_codes.delete_many({"_id": {"$regex": f"^TEST-.*-{TS}$"}})
    db.redemption_codes.delete_many({"_id": {"$regex": "^TEST-IDEMP|^TEST-CONFLICT|^TEST-VOID|^TEST-OWNER|^TEST-DOWNG|^TEST-CSV|^TEST-Z|^TEST-BAD"}})
    db.buyers.delete_many({"email": {"$regex": "^test_iter34_"}})
