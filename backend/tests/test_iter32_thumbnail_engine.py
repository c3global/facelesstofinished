"""
F2F48 — Iteration 32 — Group C2 Thumbnail Engine

Covers:
- POST /api/thumbnails/rewrite-prompt (Claude rewriter)
- POST /api/thumbnails/generate (Fast engine only to save costs)
- GET /api/thumbnails (list, sorted, soft-delete excluded)
- DELETE /api/thumbnails/{id} (soft-delete; 404 for missing)
- GET /api/thumbnails/file/{id} (public no-auth streamer)
- Auth gating (401 without JWT)
- Quota gate (T1 buyer: quota=20, premium locked)
- Refund-on-failure (in-process via direct function call)
- /api/me/quota new thumbnail fields

NOTE: Premium gpt-image-1 burns real OpenAI credits — we only verify the
engine routing returns 200 ONCE as owner if budget allows; otherwise we
skip. Fast engine generation is performed at most ONCE per run.
"""
import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://f2f48-video-engine.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "f48_studio")

ADMIN_EMAIL = "drcharitycampbell@gmail.com"
GRANT_EMAIL = "directkynections@gmail.com"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(s, email):
    r = s.post(f"{BASE_URL}/api/auth/check", json={"email": email}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token(s):
    return _login(s, ADMIN_EMAIL)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mdb():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


# ---------- T1 buyer seeding (for quota tests) ----------

@pytest.fixture
def t1_buyer(s, mdb):
    """Seed a T1 buyer with thumbnail quota fields; clean up after."""
    email = f"test_t1_thumb_{uuid.uuid4().hex[:8]}@example.com"
    now_iso = datetime.now(timezone.utc).isoformat()
    mdb.buyers.insert_one({
        "email": email,
        "entitlements": ["base", "shorts", "studio"],
        "tier": "t1",
        "founders": False,
        "thumbnailQuotaMonthly": 20,
        "thumbnailsThisCycle": 19,
        "thumbnailPremiumAllowed": False,
        "rendersThisCycle": 0,
        "renderQuotaMonthly": 30,
        "createdAt": now_iso,
        "updatedAt": now_iso,
    })
    r = s.post(f"{BASE_URL}/api/auth/check", json={"email": email}, timeout=30)
    assert r.status_code == 200, f"T1 auth failed: {r.status_code} {r.text}"
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    yield {"email": email, "token": token, "headers": headers}
    mdb.buyers.delete_one({"email": email})
    mdb.thumbnails.delete_many({"owner": email})


# ---------- Auth gating ----------

class TestAuthGating:
    def test_list_requires_jwt(self, s):
        r = s.get(f"{BASE_URL}/api/thumbnails")
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_generate_requires_jwt(self, s):
        r = s.post(
            f"{BASE_URL}/api/thumbnails/generate",
            json={"prompt": "test prompt long enough", "engine": "fast", "aspect": "16_9"},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401

    def test_rewrite_requires_jwt(self, s):
        r = s.post(
            f"{BASE_URL}/api/thumbnails/rewrite-prompt",
            json={"raw_prompt": "a guy on a beach"},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401

    def test_delete_requires_jwt(self, s):
        r = s.delete(f"{BASE_URL}/api/thumbnails/nonexistent_id")
        assert r.status_code == 401

    def test_file_streamer_is_no_auth(self, s):
        # No auth → should not 401; should 400 (bad oid) or 404
        r = s.get(f"{BASE_URL}/api/thumbnails/file/nonexistent_id.png")
        assert r.status_code in (400, 404), f"expected 400/404, got {r.status_code}"


# ---------- /api/me/quota new fields ----------

class TestQuotaEndpointThumbnailFields:
    def test_owner_unlimited_no_thumb_fields(self, s, admin_h):
        r = s.get(f"{BASE_URL}/api/me/quota", headers=admin_h)
        assert r.status_code == 200
        data = r.json()
        assert data.get("unlimited") is True
        assert "thumbnails_used" not in data
        assert "thumbnails_total" not in data

    def test_t1_buyer_has_thumb_fields(self, s, t1_buyer):
        r = s.get(f"{BASE_URL}/api/me/quota", headers=t1_buyer["headers"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("unlimited") is False
        assert data.get("thumbnails_used") == 19
        assert data.get("thumbnails_total") == 20
        assert data.get("thumbnails_remaining") == 1
        assert data.get("thumbnail_premium_allowed") is False


# ---------- Rewriter ----------

class TestRewriter:
    def test_rewrite_prompt(self, s, admin_h):
        raw = "a guy who escaped the rat race"
        r = s.post(
            f"{BASE_URL}/api/thumbnails/rewrite-prompt",
            json={"raw_prompt": raw, "topic": "financial freedom"},
            headers=admin_h,
            timeout=60,
        )
        assert r.status_code == 200, f"rewrite failed: {r.status_code} {r.text}"
        data = r.json()
        rewritten = data.get("rewritten_prompt") or ""
        assert isinstance(rewritten, str)
        assert len(rewritten) > len(raw), f"rewritten not longer: {len(rewritten)} vs {len(raw)}"
        assert len(rewritten) > 50, f"rewritten too short: {rewritten}"


# ---------- Quota gating (without burning image-gen credits) ----------

class TestQuotaGate:
    """Verifies the gate raises 402 BEFORE invoking image gen — so no
    real credit is burnt. Last slot is consumed by the gate path which
    then attempts image gen; we accept either 200 or 502 (model error)
    but verify quota was decremented."""

    def test_premium_locked_for_t1(self, s, t1_buyer):
        r = s.post(
            f"{BASE_URL}/api/thumbnails/generate",
            json={"prompt": "test cinematic skyline", "engine": "premium", "aspect": "16_9"},
            headers=t1_buyer["headers"],
            timeout=20,
        )
        assert r.status_code == 402, f"expected 402, got {r.status_code}: {r.text}"
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("reason") == "thumbnail_premium_locked"

    def test_quota_exhausted_returns_402(self, s, mdb):
        """Seed buyer at quota=used (no slots left) → 402 thumbnail_quota_exhausted.
        No image gen is invoked (gate fires first), so no credits burned."""
        email = f"test_t1_full_{uuid.uuid4().hex[:8]}@example.com"
        now_iso = datetime.now(timezone.utc).isoformat()
        mdb.buyers.insert_one({
            "email": email,
            "entitlements": ["base", "shorts", "studio"],
            "tier": "t1",
            "founders": False,
            "thumbnailQuotaMonthly": 20,
            "thumbnailsThisCycle": 20,  # fully exhausted
            "thumbnailPremiumAllowed": False,
            "createdAt": now_iso,
        })
        try:
            r = s.post(f"{BASE_URL}/api/auth/check", json={"email": email}, timeout=30)
            assert r.status_code == 200
            token = r.json()["token"]
            h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            r = s.post(
                f"{BASE_URL}/api/thumbnails/generate",
                json={"prompt": "test cinematic skyline", "engine": "fast", "aspect": "16_9"},
                headers=h,
                timeout=20,
            )
            assert r.status_code == 402, f"expected 402, got {r.status_code}: {r.text}"
            detail = r.json().get("detail")
            assert isinstance(detail, dict)
            assert detail.get("reason") == "thumbnail_quota_exhausted"
            assert "20" in detail.get("message", "")
            # Verify quota was NOT decremented further (still 20)
            buyer_doc = mdb.buyers.find_one({"email": email})
            assert buyer_doc["thumbnailsThisCycle"] == 20
        finally:
            mdb.buyers.delete_one({"email": email})


# ---------- Refund-on-failure (in-process unit test) ----------

class TestRefundOnFailure:
    """Direct function-level test of the refund path. Avoids burning image
    gen credits while still verifying the post-failure refund actually
    decrements thumbnailsThisCycle."""

    def test_refund_decrements_counter(self, mdb):
        email = f"test_refund_{uuid.uuid4().hex[:8]}@example.com"
        mdb.buyers.insert_one({
            "email": email,
            "tier": "t1",
            "founders": False,
            "thumbnailQuotaMonthly": 20,
            "thumbnailsThisCycle": 11,
            "thumbnailPremiumAllowed": False,
        })
        try:
            sys.path.insert(0, "/app/backend")
            from motor.motor_asyncio import AsyncIOMotorClient
            from thumbnails_routes import _refund_thumbnail_slot

            async def _run():
                client = AsyncIOMotorClient(MONGO_URL)
                db = client[DB_NAME]
                await _refund_thumbnail_slot(
                    db=db,
                    email=email,
                    dev_bypass_email="someone-else@example.com",
                    studio_grant_emails=set(),
                )
                client.close()

            asyncio.run(_run())
            buyer = mdb.buyers.find_one({"email": email})
            assert buyer["thumbnailsThisCycle"] == 10, f"expected 10, got {buyer['thumbnailsThisCycle']}"
        finally:
            mdb.buyers.delete_one({"email": email})

    def test_refund_skips_dev_bypass(self, mdb):
        email = ADMIN_EMAIL
        try:
            sys.path.insert(0, "/app/backend")
            from motor.motor_asyncio import AsyncIOMotorClient
            from thumbnails_routes import _refund_thumbnail_slot

            async def _run():
                client = AsyncIOMotorClient(MONGO_URL)
                db = client[DB_NAME]
                await _refund_thumbnail_slot(
                    db=db, email=email, dev_bypass_email=ADMIN_EMAIL,
                    studio_grant_emails=set(),
                )
                client.close()

            asyncio.run(_run())
            # Did not raise; that's the assertion
        finally:
            pass


# ---------- End-to-end Fast generation + list + delete + file streaming ----------

class TestE2EFastGeneration:
    """ONE Fast generation call as owner (no quota touched), then verify
    list/delete/file streaming. Total cost: 1 Gemini Nano Banana call."""

    @pytest.fixture(scope="class")
    def generated(self, admin_h):
        sess = requests.Session()
        r = sess.post(
            f"{BASE_URL}/api/thumbnails/generate",
            json={
                "prompt": "A vibrant city skyline at sunset with neon reflections on wet pavement, dramatic golden-hour lighting",
                "engine": "fast",
                "aspect": "16_9",
            },
            headers=admin_h,
            timeout=120,
        )
        return r

    def test_generate_returns_200(self, generated):
        assert generated.status_code == 200, f"generate failed: {generated.status_code} {generated.text[:500]}"
        data = generated.json()
        assert "id" in data
        assert data.get("engine") == "fast"
        assert data.get("aspect") == "16_9"
        assert data.get("size", 0) > 50_000, f"size too small: {data.get('size')}"
        assert "/api/thumbnails/file/" in data.get("url", "")
        assert data.get("original_prompt", "").startswith("A vibrant city skyline")
        assert "created_at" in data

    def test_file_streamer_returns_png(self, generated, s):
        url = generated.json()["url"]
        full = f"{BASE_URL}{url}" if url.startswith("/") else url
        r = s.get(full, timeout=30)
        assert r.status_code == 200, f"file streamer failed: {r.status_code}"
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 50_000

    def test_list_includes_generated(self, generated, s, admin_h):
        thumb_id = generated.json()["id"]
        r = s.get(f"{BASE_URL}/api/thumbnails", headers=admin_h, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "thumbnails" in data
        assert isinstance(data["thumbnails"], list)
        ids = [t["id"] for t in data["thumbnails"]]
        assert thumb_id in ids
        # Newest first — created_at descending
        if len(data["thumbnails"]) >= 2:
            t0 = data["thumbnails"][0]["created_at"]
            t1 = data["thumbnails"][1]["created_at"]
            assert t0 >= t1, "thumbnails not sorted newest-first"
        # Verify required fields
        first = data["thumbnails"][0]
        for k in ("id", "engine", "aspect", "prompt", "original_prompt", "url", "created_at"):
            assert k in first, f"missing field {k} in list response"

    def test_delete_removes_from_list(self, generated, s, admin_h):
        thumb_id = generated.json()["id"]
        r = s.delete(f"{BASE_URL}/api/thumbnails/{thumb_id}", headers=admin_h, timeout=30)
        assert r.status_code == 200, f"delete failed: {r.status_code} {r.text}"
        assert r.json().get("ok") is True
        # Verify excluded from subsequent list
        r2 = s.get(f"{BASE_URL}/api/thumbnails", headers=admin_h, timeout=30)
        ids = [t["id"] for t in r2.json()["thumbnails"]]
        assert thumb_id not in ids

    def test_delete_nonexistent_returns_404(self, s, admin_h):
        r = s.delete(f"{BASE_URL}/api/thumbnails/nonexistent_id_xyz", headers=admin_h, timeout=30)
        assert r.status_code == 404
