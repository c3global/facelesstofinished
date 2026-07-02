"""
Iter 36 — Follow-ups on Group E (BYOK) + thumbnail lightbox.

Backend test coverage:
1) REGRESSION: GET /api/me/quota for the DEV_BYPASS owner returns
   byok_allowed=True (was previously omitted).
2) BYOK Anthropic: GET /api/user/byok lists 4 services (anthropic, openai,
   heygen, fal) with the expected label/purpose/hint metadata.
3) BYOK Anthropic save/get/delete cycle works with a fake key.
4) Static source inspection for the BYOK Anthropic wiring in:
     - server.py _claude_complete signature includes user_email
     - both /scripts/angles + /studio/broll-prompts callers pass user.email
     - server.py _run_script_job receives user_email and uses get_byok_key('anthropic')
     - thumbnails_routes.py rewrite-prompt + concepts-from-script use
       get_byok_key for 'anthropic' before falling back to Emergent LLM key.
"""

import os
import re
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
SERVER_PY = "/app/backend/server.py"
THUMBS_PY = "/app/backend/thumbnails_routes.py"
BYOK_PY = "/app/backend/byok_routes.py"


# ---------- Helpers ----------
def _owner_auth() -> dict:
    r = requests.post(f"{API}/auth/check", json={"email": OWNER_EMAIL}, timeout=10)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def owner_h():
    h = _owner_auth()
    # Pre-cleanup any leftover anthropic key from previous runs
    db.byok_keys.delete_many({"email": OWNER_EMAIL, "service": "anthropic"})
    yield h
    db.byok_keys.delete_many({"email": OWNER_EMAIL, "service": "anthropic"})


# ============================================================================
# 1) REGRESSION — /api/me/quota now includes byok_allowed for owner
# ============================================================================
class TestMeQuotaRegression:
    def test_owner_quota_has_byok_allowed_true(self, owner_h):
        r = requests.get(f"{API}/me/quota", headers=owner_h, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("unlimited") is True
        assert "byok_allowed" in body, f"byok_allowed missing from {body}"
        assert body["byok_allowed"] is True, body


# ============================================================================
# 2) BYOK Anthropic service metadata
# ============================================================================
class TestByokAnthropicServiceList:
    def test_list_has_four_services_with_anthropic(self, owner_h):
        r = requests.get(f"{API}/user/byok", headers=owner_h, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("byok_allowed") is True
        ids = [s["id"] for s in body["services"]]
        assert set(ids) == {"anthropic", "openai", "heygen", "fal"}, ids

        anth = next(s for s in body["services"] if s["id"] == "anthropic")
        assert anth["label"] == "Anthropic"
        assert "Script Engine" in anth["purpose"]
        assert "thumbnail prompt rewriter" in anth["purpose"]
        assert "sk-ant-" in anth["key_hint"]
        assert anth["configured"] is False  # cleaned up in fixture


# ============================================================================
# 3) Save / Get / Delete cycle for the anthropic service
# ============================================================================
class TestByokAnthropicCRUD:
    def test_save_get_delete_anthropic_key(self, owner_h):
        fake_key = "sk-ant-test-iter36-" + uuid.uuid4().hex

        # Save
        r = requests.post(
            f"{API}/user/byok",
            json={"service": "anthropic", "key": fake_key},
            headers=owner_h,
            timeout=10,
        )
        assert r.status_code == 200, r.text
        save_body = r.json()
        assert save_body.get("ok") is True
        # Masked hint, never full plaintext
        for v in save_body.values():
            assert fake_key not in str(v)

        # GET — anthropic shows configured=true; plaintext NEVER returned
        r = requests.get(f"{API}/user/byok", headers=owner_h, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        anth = next(s for s in body["services"] if s["id"] == "anthropic")
        assert anth["configured"] is True
        # No field anywhere in the response leaks the plaintext
        assert fake_key not in r.text

        # DB sanity: encrypted_key starts with Fernet token prefix gAAAAA,
        # and the plaintext is not present anywhere in the document.
        doc = db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "anthropic"})
        assert doc is not None
        assert doc["encrypted_key"].startswith("gAAAAA"), doc["encrypted_key"][:20]
        assert fake_key not in doc["encrypted_key"]

        # Delete
        r = requests.delete(f"{API}/user/byok/anthropic", headers=owner_h, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Confirm removed
        r = requests.get(f"{API}/user/byok", headers=owner_h, timeout=10)
        anth = next(s for s in r.json()["services"] if s["id"] == "anthropic")
        assert anth["configured"] is False
        assert db.byok_keys.find_one({"email": OWNER_EMAIL, "service": "anthropic"}) is None

    def test_short_anthropic_key_rejected(self, owner_h):
        r = requests.post(
            f"{API}/user/byok",
            json={"service": "anthropic", "key": "short"},
            headers=owner_h,
            timeout=10,
        )
        assert r.status_code in (400, 422), r.text


# ============================================================================
# 4) Static source inspection — BYOK Anthropic wiring
# ============================================================================
class TestByokAnthropicWiringStatic:
    @classmethod
    def setup_class(cls):
        with open(SERVER_PY) as fh:
            cls.server_src = fh.read()
        with open(THUMBS_PY) as fh:
            cls.thumbs_src = fh.read()
        with open(BYOK_PY) as fh:
            cls.byok_src = fh.read()

    # 4a) _claude_complete signature has user_email + does BYOK lookup
    def test_claude_complete_has_user_email_and_byok(self):
        # Locate the function header (anchor) — supports multi-line signatures
        # AND a `) -> str:` return-type annotation.
        idx = self.server_src.find("async def _claude_complete(")
        assert idx >= 0, "_claude_complete not defined"
        m = re.search(r"\)\s*(->\s*[^:]+)?:", self.server_src[idx:])
        assert m, "Could not find end of _claude_complete signature"
        sig_end = idx + m.end()
        sig = self.server_src[idx:sig_end]
        assert "user_email" in sig, f"user_email missing from signature: {sig}"
        # Grab function body (up to next top-level async def / def / class).
        body_start = sig_end
        nxt_async = self.server_src.find("\nasync def ", body_start + 1)
        nxt_def = self.server_src.find("\ndef ", body_start + 1)
        candidates = [c for c in (nxt_async, nxt_def) if c > 0]
        body_end = min(candidates) if candidates else len(self.server_src)
        body = self.server_src[body_start:body_end]
        assert 'get_byok_key(db, user_email, "anthropic")' in body
        assert "_anthropic_direct_complete" in body

    # 4b) angles + broll-prompts callers pass user.email
    def test_callers_pass_user_email(self):
        # broll-prompts caller
        assert "_claude_complete(BROLL_PROMPTS_SYSTEM" in self.server_src
        broll_idx = self.server_src.find("_claude_complete(BROLL_PROMPTS_SYSTEM")
        broll_call = self.server_src[broll_idx:broll_idx + 400]
        assert "user_email=user.email" in broll_call, broll_call
        # angles caller
        assert "_claude_complete(ANGLES_SYSTEM_PROMPT" in self.server_src
        ang_idx = self.server_src.find("_claude_complete(ANGLES_SYSTEM_PROMPT")
        ang_call = self.server_src[ang_idx:ang_idx + 400]
        assert "user_email=user.email" in ang_call, ang_call

    # 4c) _run_script_job receives user_email + uses get_byok_key('anthropic')
    def test_run_script_job_has_user_email_and_byok(self):
        m = re.search(
            r"async def _run_script_job\([^)]*user_email[^)]*\):(.*?)(?=\nasync def |\ndef |\Z)",
            self.server_src,
            flags=re.DOTALL,
        )
        assert m, "_run_script_job must include user_email parameter"
        body = m.group(1)
        assert 'get_byok_key(db, user_email, "anthropic")' in body, body[:600]
        # Has fallback to platform key (Emergent LLM via LlmChat)
        assert "_anthropic_direct_stream" in body or "LlmChat" in self.server_src
        # Enqueue site passes user.email
        assert re.search(
            r"_run_script_job\([^)]*user_email=user\.email",
            self.server_src,
            flags=re.DOTALL,
        ), "_enqueue_script call must pass user_email=user.email"

    # 4d) thumbnails_routes.py rewrite-prompt has BYOK anthropic branch
    def test_thumbnails_rewrite_prompt_byok_branch(self):
        idx = self.thumbs_src.find('"/thumbnails/rewrite-prompt"')
        assert idx >= 0, "rewrite-prompt route not found"
        # Block: from this decorator to the next @api.post or end of module.
        nxt = self.thumbs_src.find("@api.post(", idx + 1)
        block = self.thumbs_src[idx: nxt if nxt > 0 else len(self.thumbs_src)]
        assert 'get_byok_key(db, user.email, "anthropic")' in block, block[:600]
        assert "api.anthropic.com/v1/messages" in block
        # Must fall back to LlmChat (Emergent path) when no BYOK key
        assert "LlmChat" in self.thumbs_src

    # 4e) thumbnails_routes.py concepts-from-script has BYOK anthropic branch
    def test_thumbnails_concepts_from_script_byok_branch(self):
        idx = self.thumbs_src.find('"/thumbnails/concepts-from-script"')
        assert idx >= 0, "concepts-from-script route not found"
        nxt = self.thumbs_src.find("@api.post(", idx + 1)
        block = self.thumbs_src[idx: nxt if nxt > 0 else len(self.thumbs_src)]
        assert 'get_byok_key(db, user.email, "anthropic")' in block, block[:600]
        assert "api.anthropic.com/v1/messages" in block

    # 4f) byok_routes.py SERVICES dict has anthropic FIRST + correct metadata
    def test_byok_services_dict(self):
        assert re.search(
            r'SERVICES:\s*dict\[str,\s*dict\]\s*=\s*\{\s*"anthropic"',
            self.byok_src,
        ), "anthropic must be the first key in SERVICES"
        # All 4 services declared
        for svc in ("anthropic", "openai", "heygen", "fal"):
            assert f'"{svc}"' in self.byok_src
