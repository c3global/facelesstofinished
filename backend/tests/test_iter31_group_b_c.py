"""
F2F48 — Iteration 31 — Group B Quota Infrastructure + Group C tests

Covers:
- GET /api/me/quota (owner/dev_bypass unlimited + non-founder buyer fields)
- POST /api/activity/log (allowlist + 4 types + disallowed type)
- POST /api/studio/render/both-aspects quota gating + refund on mid-batch 402
- GET /api/admin/buyers/export & /api/admin/usage/export (CSV filename, BOM, headers)
- Admin auth gating + JWT gating

All tests against the public REACT_APP_BACKEND_URL.
Test data uses TEST_ email prefix and is cleaned up after each test.
"""
import os
import re
import uuid
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://modal-chip-ui.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "f48_studio")

ADMIN_EMAIL = "drcharitycampbell@gmail.com"   # dev bypass + admin
GRANT_EMAIL = "directkynections@gmail.com"     # STUDIO_GRANT, non-admin


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(s, email):
    r = s.post(f"{BASE_URL}/api/auth/check", json={"email": email})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token(s):
    return _login(s, ADMIN_EMAIL)


@pytest.fixture(scope="module")
def grant_token(s):
    return _login(s, GRANT_EMAIL)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def grant_h(grant_token):
    return {"Authorization": f"Bearer {grant_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mdb():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


# ---------- /api/me/quota ----------

class TestQuotaEndpoint:
    def test_quota_owner_unlimited(self, s, admin_h):
        r = s.get(f"{BASE_URL}/api/me/quota", headers=admin_h)
        assert r.status_code == 200
        d = r.json()
        assert d.get("unlimited") is True
        assert d.get("tier_id") == "owner"
        assert d.get("tier_label") == "Owner"

    def test_quota_grant_unlimited(self, s, grant_h):
        # STUDIO_GRANT email also gets unlimited treatment
        r = s.get(f"{BASE_URL}/api/me/quota", headers=grant_h)
        assert r.status_code == 200
        d = r.json()
        assert d.get("unlimited") is True

    def test_quota_no_token_401(self, s):
        r = requests.get(f"{BASE_URL}/api/me/quota")
        assert r.status_code in (401, 403)

    def test_quota_non_founder_buyer_fields(self, s, mdb):
        # Seed a non-founder buyer + grant entitlements + add to DB,
        # then login through buyer path.
        email = f"test_quota_{uuid.uuid4().hex[:8]}@example.com"

        mdb.buyers.insert_one({
            "email": email,
            "entitlements": ["base", "shorts", "studio"],
            "tier": "t3",
            "founders": False,
            "rendersThisCycle": 2,
            "renderQuotaMonthly": 15,
            "avatarRendersThisCycle": 0,
            "avatarSubCap": 5,
            "monthlyCostCents": 0,
            "monthlyCostCapCents": 500,
            "cycleStartedAt": "2026-01-01T00:00:00+00:00",
            "cycleResetsAt": "2026-02-01T00:00:00+00:00",
            "addedAt": datetime.now(timezone.utc).isoformat(),
        })
        try:
            tok = _login(s, email)
            h = {"Authorization": f"Bearer {tok}"}
            r = s.get(f"{BASE_URL}/api/me/quota", headers=h)
            assert r.status_code == 200
            d = r.json()
            assert d.get("unlimited") is False
            for k in ("renders_used", "renders_total", "renders_remaining",
                      "avatar_used", "avatar_cap", "avatar_remaining",
                      "cycle_started_at", "cycle_resets_at",
                      "tier_id", "tier_label"):
                assert k in d, f"missing field {k}"
            assert d["renders_used"] == 2
            assert d["renders_total"] == 15
            assert d["renders_remaining"] == 13
            assert d["tier_id"] == "t3"
        finally:
            mdb.buyers.delete_many({"email": email})


# ---------- /api/activity/log ----------

class TestActivityLog:
    @pytest.mark.parametrize("ev", [
        "script_copied", "script_sent_to_studio",
        "video_played", "script_opened_from_history",
    ])
    def test_activity_allowed_types(self, s, admin_h, mdb, ev):
        r = s.post(f"{BASE_URL}/api/activity/log",
                   headers=admin_h, json={"type": ev, "detail": {"k": "v"}})
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # Verify persistence (search recent docs for matching type)
        doc = mdb.activity.find_one(
            {"type": ev, "email": ADMIN_EMAIL},
            sort=[("created_at", -1)],
        )
        assert doc is not None, f"activity doc not found for type={ev}"

    def test_activity_disallowed_type(self, s, admin_h):
        r = s.post(f"{BASE_URL}/api/activity/log",
                   headers=admin_h, json={"type": "random_event"})
        assert r.status_code == 200
        assert r.json().get("ok") is False

    def test_activity_no_token_401(self, s):
        r = requests.post(f"{BASE_URL}/api/activity/log",
                          json={"type": "script_copied"})
        assert r.status_code in (401, 403)


# ---------- studio/render/both-aspects quota gate + refund ----------

class TestBothAspectsQuotaRefund:
    def test_quota_gate_refunds_on_mid_batch_failure(self, s, mdb):
        """Seed buyer with quota=2, used=1 -> first aspect (9_16) eats slot,
        second aspect (16_9) exceeds cap and raises 402, MUST refund the
        first slot so rendersThisCycle ends at 1."""
        email = f"test_refund_{uuid.uuid4().hex[:8]}@example.com"

        mdb.buyers.insert_one({
            "email": email,
            "entitlements": ["base", "shorts", "studio"],
            "tier": "t3",
            "founders": False,
            "rendersThisCycle": 1,
            "renderQuotaMonthly": 2,
            "avatarRendersThisCycle": 0,
            "avatarSubCap": 5,
            "monthlyCostCents": 0,
            "monthlyCostCapCents": 5000,
            "addedAt": datetime.now(timezone.utc).isoformat(),
        })
        try:
            tok = _login(s, email)
            h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

            payload = {
                "mode": "faceless",
                "aspect": "9_16",
                "captions": True,
                "script": "Hello world TEST script for refund flow.",
                "avatar_id": None,
                "voice_id": None,
                "tts_voice_id": None,
                "broll_source": "pexels",
                "scenes": [
                    {"text": "scene one", "duration": 4},
                    {"text": "scene two", "duration": 4},
                ],
                "ai_engine": "kokoro",
            }
            r = s.post(f"{BASE_URL}/api/studio/render/both-aspects",
                       headers=h, json=payload)
            # Should fail with 402 — first aspect eats last slot,
            # second aspect cannot be gated
            assert r.status_code == 402, f"expected 402, got {r.status_code}: {r.text}"

            # Verify refund — buyer rendersThisCycle must still be 1
            buyer = mdb.buyers.find_one({"email": email})
            assert buyer["rendersThisCycle"] == 1, (
                f"refund failed: rendersThisCycle={buyer['rendersThisCycle']}, expected 1"
            )
        finally:
            mdb.buyers.delete_many({"email": email})
            mdb.renders.delete_many({"user_email": email})
            mdb.activity.delete_many({"email": email})


# ---------- CSV exports ----------

_FILENAME_RE = re.compile(r"F2F48-(buyers|usage)-(\d{4}-\d{2}-\d{2})-export\.csv")


class TestCsvExports:
    def test_buyers_export_admin(self, s, admin_h):
        r = s.get(f"{BASE_URL}/api/admin/buyers/export", headers=admin_h, stream=True)
        assert r.status_code == 200
        ctype = r.headers.get("Content-Type", "")
        assert "text/csv" in ctype.lower()
        cd = r.headers.get("Content-Disposition", "")
        m = _FILENAME_RE.search(cd)
        assert m and m.group(1) == "buyers", f"bad Content-Disposition: {cd}"
        # Verify the YYYY-MM-DD ISO date format matches today (UTC)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert m.group(2) == today
        # Stream first chunk to check BOM + header
        head = r.raw.read(512).decode("utf-8", errors="ignore")
        assert head.startswith("\ufeff"), "missing UTF-8 BOM"
        # First line: header row
        first_line = head.splitlines()[0]
        for col in ("email", "tier", "founder", "entitlements"):
            assert col in first_line, f"missing column {col} in header: {first_line}"

    def test_usage_export_admin(self, s, admin_h):
        r = s.get(f"{BASE_URL}/api/admin/usage/export", headers=admin_h, stream=True)
        assert r.status_code == 200
        ctype = r.headers.get("Content-Type", "")
        assert "text/csv" in ctype.lower()
        cd = r.headers.get("Content-Disposition", "")
        m = _FILENAME_RE.search(cd)
        assert m and m.group(1) == "usage", f"bad Content-Disposition: {cd}"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert m.group(2) == today
        head = r.raw.read(2048).decode("utf-8", errors="ignore")
        assert head.startswith("\ufeff"), "missing UTF-8 BOM"
        first_line = head.splitlines()[0]
        for col in ("email", "tier", "founder", "entitlements", "scripts_total"):
            assert col in first_line, f"missing column {col} in header: {first_line}"

    def test_buyers_export_non_admin_403(self, s, grant_h):
        r = s.get(f"{BASE_URL}/api/admin/buyers/export", headers=grant_h)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_usage_export_non_admin_403(self, s, grant_h):
        r = s.get(f"{BASE_URL}/api/admin/usage/export", headers=grant_h)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"
