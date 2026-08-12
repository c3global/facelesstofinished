"""Iter-30 Group A foundation: comprehensive regression coverage.

Verifies the four atomic changes shipped in Group A of the AppSumo launch
plan:

  1. lastLoginAt + loginCount stamping on every successful /api/auth/check
     resolution path (DEV_BYPASS, STUDIO_GRANT, db.buyers).
  2. /app/backend/tier_config.py pure-data integrity — get_tier(),
     tier_for_entitlements(), sticker/quota/avatar/byok values per spec.
  3. GET /api/admin/usage shape, sort, filter, validation, aggregation
     correctness with seeded scripts + renders.
  4. GET /api/admin/usage as a non-admin returns 403.

Run with:
  cd /app/backend && pytest tests/test_iter30_group_a_foundation.py -v \
    --tb=short --junitxml=/app/test_reports/pytest/iter30.xml
"""
import os
import time
import uuid
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Backend env (MONGO_URL, DB_NAME) — required for direct buyer/scripts/renders
# fixtures. We deliberately read from the backend .env so the test stays in
# sync with the running server's actual database.
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://modal-chip-ui.preview.emergentagent.com"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
ADMIN_EMAIL = "drcharitycampbell@gmail.com"

# Test data prefix — every seeded buyer/script/render uses this email prefix
# so the teardown cleanup is bullet-proof and we never touch real buyers.
TEST_PREFIX = "test_iter30_"


# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture(scope="module")
def event_loop():
    """Shared loop for all module-scoped async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db(event_loop):
    """Direct Motor handle on the live preview DB."""
    client = AsyncIOMotorClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def admin_token():
    """Sign in the DEV_BYPASS admin once for the whole module."""
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": ADMIN_EMAIL}, timeout=10)
    assert r.status_code == 200, f"admin auth failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="function")
def cleanup(event_loop, db):
    """Per-test teardown — purges every test_iter30_* email across collections."""
    yield

    async def _purge():
        await db.buyers.delete_many({"email": {"$regex": f"^{TEST_PREFIX}"}})
        await db.scripts.delete_many({"user_email": {"$regex": f"^{TEST_PREFIX}"}})
        await db.renders.delete_many({"user_email": {"$regex": f"^{TEST_PREFIX}"}})

    event_loop.run_until_complete(_purge())


# ============================================================================
# 1. lastLoginAt stamping — DEV_BYPASS path
# ============================================================================
class TestAuthLastLoginStamp:
    """Verifies the new _stamp_last_login() helper writes on EVERY successful
    sign-in resolution path."""

    def test_dev_bypass_stamps_last_login(self, event_loop, db):
        """DEV_BYPASS admin → lastLoginAt + updatedAt + loginCount written."""
        # Ensure a buyer record exists for the admin so update_one(upsert=False)
        # has a target. If it doesn't, we create one so we can read back the
        # stamp afterward (the admin may not have a row in clean preview dbs).
        async def _ensure_admin_buyer():
            existing = await db.buyers.find_one({"email": ADMIN_EMAIL})
            if not existing:
                await db.buyers.insert_one({
                    "email": ADMIN_EMAIL,
                    "entitlements": ["base", "shorts", "studio"],
                    "addedAt": datetime.now(timezone.utc).isoformat(),
                    "loginCount": 0,
                })
            return await db.buyers.find_one({"email": ADMIN_EMAIL})

        before = event_loop.run_until_complete(_ensure_admin_buyer())
        prev_count = int(before.get("loginCount") or 0)

        r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": ADMIN_EMAIL}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "token" in body and body["user"]["isAdmin"] is True

        after = event_loop.run_until_complete(db.buyers.find_one({"email": ADMIN_EMAIL}))
        assert after is not None, "admin buyer row vanished after sign-in"
        assert after.get("lastLoginAt"), "lastLoginAt was not stamped"

        # FRESH within the last 60 seconds
        stamped = datetime.fromisoformat(after["lastLoginAt"])
        age = (datetime.now(timezone.utc) - stamped).total_seconds()
        assert 0 <= age < 60, f"lastLoginAt is {age:.1f}s old — not fresh"

        # updatedAt must match lastLoginAt (same $set call)
        assert after.get("updatedAt") == after["lastLoginAt"]

        # loginCount incremented by 1
        new_count = int(after.get("loginCount") or 0)
        assert new_count == prev_count + 1, (
            f"loginCount {prev_count} → {new_count} (expected +1)"
        )

    def test_buyer_lookup_path_stamps_last_login(self, event_loop, db, cleanup):
        """Buyer-lookup path (NOT DEV_BYPASS, NOT STUDIO_GRANT) → stamped."""
        email = f"{TEST_PREFIX}buyerpath_{uuid.uuid4().hex[:8]}@example.com"

        async def _seed():
            await db.buyers.insert_one({
                "email": email,
                "entitlements": ["base", "shorts"],
                "addedAt": datetime.now(timezone.utc).isoformat(),
                "loginCount": 0,
            })

        event_loop.run_until_complete(_seed())

        r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": email}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["isAdmin"] is False
        assert "base" in body["user"]["entitlements"]

        after = event_loop.run_until_complete(db.buyers.find_one({"email": email}))
        assert after.get("lastLoginAt"), "buyer-lookup path did not stamp lastLoginAt"
        stamped = datetime.fromisoformat(after["lastLoginAt"])
        age = (datetime.now(timezone.utc) - stamped).total_seconds()
        assert age < 60, f"buyer-path lastLoginAt {age:.1f}s old"
        assert int(after.get("loginCount") or 0) == 1


# ============================================================================
# 2. tier_config.py — pure data integrity
# ============================================================================
class TestTierConfig:
    """tier_config.py must be importable with no DB writes and produce
    deterministic values per spec."""

    def test_tiers_by_id_has_five_keys(self):
        from tier_config import TIERS_BY_ID
        assert set(TIERS_BY_ID.keys()) == {"t1", "t2", "t3", "t4", "founder"}

    def test_get_tier_t3_values(self):
        from tier_config import get_tier
        t3 = get_tier("t3")
        assert t3.id == "t3"
        assert t3.sticker_cents == 17_900
        assert t3.render_quota_monthly == 15
        assert t3.avatar_sub_cap == 5
        assert t3.byok_allowed is False

    def test_get_tier_none_falls_back_to_t1(self):
        from tier_config import get_tier, TIER_T1
        assert get_tier(None) is TIER_T1
        # unknown id also falls back (defensive)
        assert get_tier("nonsense").id == "t1"

    @pytest.mark.parametrize("ents,expected_id", [
        (["base"], "t1"),
        (["base", "shorts"], "t2"),
        (["base", "shorts", "studio"], "t3"),
        (["base", "shorts", "studio", "byok"], "t4"),
    ])
    def test_tier_for_entitlements_mapping(self, ents, expected_id):
        from tier_config import tier_for_entitlements
        assert tier_for_entitlements(ents).id == expected_id

    def test_byok_without_studio_does_not_upgrade_to_t4(self):
        """byok requires studio — guards against weird partial entitlement sets."""
        from tier_config import tier_for_entitlements
        # byok alone w/o studio should NOT promote to t4
        assert tier_for_entitlements(["base", "byok"]).id == "t1"

    def test_founder_tier_grandfathered_unlimited(self):
        from tier_config import TIERS_BY_ID
        founder = TIERS_BY_ID["founder"]
        assert founder.is_founder_grandfather is True
        assert founder.monthly_cost_cap_cents == 0
        assert founder.render_quota_monthly >= 9_999


# ============================================================================
# 3. GET /api/admin/usage — shape, sort, filter, validation
# ============================================================================
class TestAdminUsageEndpoint:
    """Shape + control-plane behavior of the new leaderboard endpoint."""

    def test_admin_usage_returns_expected_shape(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/usage", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("total", "items", "sort_by", "sort_dir"):
            assert key in body, f"missing top-level key {key!r}"

        if body["items"]:
            row = body["items"][0]
            required = {
                "email", "tier", "entitlements", "founder", "last_seen",
                "added_at", "login_count", "scripts", "renders",
                "spend_cents", "buyer_total_spend_cents",
            }
            assert required.issubset(row.keys()), (
                f"row missing keys: {required - row.keys()}"
            )
            for k in ("total", "long", "shorts", "sprint", "last_at"):
                assert k in row["scripts"]
            for k in ("total", "faceless", "avatar", "complete", "failed", "last_at"):
                assert k in row["renders"]
            assert isinstance(row["founder"], bool)

    def test_admin_usage_requires_admin_403_for_non_admin(self, event_loop, db, cleanup):
        """Sign in as a non-admin buyer → 403 on /admin/usage."""
        email = f"{TEST_PREFIX}nonadmin_{uuid.uuid4().hex[:8]}@example.com"
        event_loop.run_until_complete(db.buyers.insert_one({
            "email": email,
            "entitlements": ["base"],
            "addedAt": datetime.now(timezone.utc).isoformat(),
        }))
        r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": email}, timeout=10)
        assert r.status_code == 200
        non_admin_token = r.json()["token"]
        assert r.json()["user"]["isAdmin"] is False

        r2 = requests.get(
            f"{BASE_URL}/api/admin/usage",
            headers={"Authorization": f"Bearer {non_admin_token}"},
            timeout=10,
        )
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"

    def test_admin_usage_sort_by_spend_desc(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?sort_by=spend_cents&sort_dir=desc",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        if len(items) >= 2:
            spends = [it["spend_cents"] for it in items]
            assert spends == sorted(spends, reverse=True), f"not sorted desc: {spends[:5]}"

    def test_admin_usage_sort_by_email_asc(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?sort_by=email&sort_dir=asc",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        if len(items) >= 2:
            emails = [it["email"].lower() for it in items]
            assert emails == sorted(emails)

    def test_admin_usage_filter_q_case_insensitive(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?q=DrCh",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert "drch" in it["email"].lower()

    def test_admin_usage_invalid_sort_by_returns_422(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?sort_by=invalid_col",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 422, f"expected 422 regex rejection, got {r.status_code}"


# ============================================================================
# 4. /admin/usage — aggregation correctness with seeded data
# ============================================================================
class TestAdminUsageAggregation:
    """End-to-end seeded aggregation: 3 scripts + 2 renders → row matches."""

    def test_seeded_aggregation_matches(self, event_loop, db, admin_headers, cleanup):
        email = f"{TEST_PREFIX}agg_{uuid.uuid4().hex[:8]}@example.com"
        now = datetime.now(timezone.utc).isoformat()

        async def _seed():
            await db.buyers.insert_one({
                "email": email,
                "entitlements": ["base", "shorts", "studio"],
                "addedAt": now,
                "loginCount": 0,
            })
            # 3 scripts: 1 long, 1 shorts, 1 sprint
            await db.scripts.insert_many([
                {"user_email": email, "mode": "long",   "created_at": now, "_seed": True},
                {"user_email": email, "mode": "shorts", "created_at": now, "_seed": True},
                {"user_email": email, "mode": "sprint", "created_at": now, "_seed": True},
            ])
            # 2 renders: 1 faceless complete (123¢), 1 avatar failed (45¢)
            await db.renders.insert_many([
                {"user_email": email, "mode": "faceless", "status": "complete",
                 "actual_cost_cents": 123, "created_at": now, "_seed": True},
                {"user_email": email, "mode": "avatar", "status": "failed",
                 "actual_cost_cents": 45, "created_at": now, "_seed": True},
            ])

        event_loop.run_until_complete(_seed())

        # Filter to just our seeded row using the q substring
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?q={TEST_PREFIX}agg",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        rows = [it for it in items if it["email"] == email]
        assert len(rows) == 1, f"expected 1 seeded row, got {len(rows)}: {items}"
        row = rows[0]

        assert row["scripts"] == {
            "total": 3, "long": 1, "shorts": 1, "sprint": 1,
            "last_at": row["scripts"]["last_at"],
        }
        assert row["renders"]["total"] == 2
        assert row["renders"]["faceless"] == 1
        assert row["renders"]["avatar"] == 1
        assert row["renders"]["complete"] == 1
        assert row["renders"]["failed"] == 1
        assert row["spend_cents"] == 168, f"expected 123+45=168, got {row['spend_cents']}"
        # tier auto-resolves from entitlements (base+shorts+studio → t3)
        assert row["tier"] == "t3"

    @pytest.mark.parametrize("ents,expected_tier", [
        (["base"], "t1"),
        (["base", "shorts"], "t2"),
        (["base", "shorts", "studio"], "t3"),
        (["base", "shorts", "studio", "byok"], "t4"),
    ])
    def test_tier_auto_resolution_in_usage_row(
        self, event_loop, db, admin_headers, cleanup, ents, expected_tier,
    ):
        email = f"{TEST_PREFIX}tier_{expected_tier}_{uuid.uuid4().hex[:6]}@example.com"
        event_loop.run_until_complete(db.buyers.insert_one({
            "email": email,
            "entitlements": ents,
            "addedAt": datetime.now(timezone.utc).isoformat(),
        }))
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?q={TEST_PREFIX}tier_{expected_tier}",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        rows = [it for it in r.json()["items"] if it["email"] == email]
        assert len(rows) == 1
        assert rows[0]["tier"] == expected_tier
        assert rows[0]["founder"] is False

    def test_founder_flag_separate_from_tier_field(self, event_loop, db, admin_headers, cleanup):
        """A founder=true buyer with byok entitlement still resolves to t4 in
        the `tier` field, but `founder` bool on the row is true."""
        email = f"{TEST_PREFIX}founder_{uuid.uuid4().hex[:6]}@example.com"
        event_loop.run_until_complete(db.buyers.insert_one({
            "email": email,
            "entitlements": ["base", "shorts", "studio", "byok"],
            "founders": True,
            "addedAt": datetime.now(timezone.utc).isoformat(),
        }))
        r = requests.get(
            f"{BASE_URL}/api/admin/usage?q={TEST_PREFIX}founder",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        rows = [it for it in r.json()["items"] if it["email"] == email]
        assert len(rows) == 1
        assert rows[0]["founder"] is True
        # tier field still resolves from entitlements
        assert rows[0]["tier"] == "t4"
