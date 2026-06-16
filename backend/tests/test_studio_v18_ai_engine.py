"""
Iteration 12 — F2F48 Studio v1.8.0 backend test:
- Passwordless admin auth
- /studio/render/estimate cost scaling across 4 AI engines (flux/kling/veo3/pika)
- /studio/render/both-aspects endpoint shape (with immediate bulk-delete to
  avoid real fal.ai spend)

Run: pytest /app/backend/tests/test_studio_v18_ai_engine.py -v
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://f2f48-video-engine.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "drcharitycampbell@gmail.com"


# --- Shared session + auth ------------------------------------------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/check", json={"email": ADMIN_EMAIL}, timeout=20)
    assert r.status_code == 200, f"/auth/check failed: {r.status_code} {r.text}"
    body = r.json()
    assert "token" in body, f"No token: {body}"
    assert body.get("user", {}).get("email", "").lower() == ADMIN_EMAIL
    # NOTE: /auth/check's user object does NOT carry isAdmin — that's surfaced
    # by /auth/me. The task spec wrongly assumed it; verifying via /auth/me below.
    return body["token"]


@pytest.fixture(scope="session")
def auth_client(admin_token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {admin_token}",
    })
    return s


# --- Auth ----------------------------------------------------------------
class TestAuth:
    def test_admin_passwordless_login(self, admin_token):
        assert isinstance(admin_token, str)
        assert len(admin_token) > 20

    def test_auth_me_returns_admin(self, auth_client):
        r = auth_client.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("email", "").lower() == ADMIN_EMAIL
        assert me.get("isAdmin") is True
        ents = me.get("entitlements") or []
        assert "studio" in ents, f"Missing studio entitlement: {ents}"


# --- Estimate endpoint cost scaling -------------------------------------
def _estimate_payload(engine: str) -> dict:
    return {
        "mode": "faceless",
        "script": "Hello world this is a short test.",
        "aspect": "9_16",
        "ai_engine": engine,
        "broll_source": "ai",
        "scenes": [
            {"source": "ai", "prompt": "sunset"},
            {"source": "ai", "prompt": "city"},
        ],
    }


# Expected cents = ceil(script_chars/1000 * 5) + ai_scenes * engine_cost + compose(2)
# script "Hello world this is a short test." = 33 chars → TTS = 0.165c
# 2 AI scenes → engine_cost * 2
# + 2c compose
# round(0.165 + 2*engine + 2) = 2*engine + 2 (since 0.165 rounds away)
EXPECTED = {
    "flux":  {"min": 8,   "max": 12,   "label": "~10c"},
    "kling": {"min": 100, "max": 105,  "label": "~$1.02"},
    "veo3":  {"min": 200, "max": 205,  "label": "~$2.02"},
    "pika":  {"min": 80,  "max": 85,   "label": "~$0.82"},
}


class TestEstimateAiEngine:
    @pytest.mark.parametrize("engine", ["flux", "kling", "veo3", "pika"])
    def test_estimate_scales_with_engine(self, auth_client, engine):
        r = auth_client.post(f"{API}/studio/render/estimate", json=_estimate_payload(engine), timeout=15)
        assert r.status_code == 200, f"engine={engine}: {r.status_code} {r.text}"
        body = r.json()
        # Endpoint may return {"estimated_cost_cents": N} or just an int
        cents = body.get("estimated_cost_cents") if isinstance(body, dict) else body
        assert isinstance(cents, int), f"engine={engine}: cents not int → {body}"
        exp = EXPECTED[engine]
        assert exp["min"] <= cents <= exp["max"], (
            f"engine={engine} expected {exp['label']} ({exp['min']}-{exp['max']}c) got {cents}c"
        )

    def test_estimate_kling_higher_than_flux(self, auth_client):
        r1 = auth_client.post(f"{API}/studio/render/estimate", json=_estimate_payload("flux"), timeout=15).json()
        r2 = auth_client.post(f"{API}/studio/render/estimate", json=_estimate_payload("kling"), timeout=15).json()
        c1 = r1.get("estimated_cost_cents") if isinstance(r1, dict) else r1
        c2 = r2.get("estimated_cost_cents") if isinstance(r2, dict) else r2
        assert c2 > c1 * 5, f"kling ({c2}) should be much higher than flux ({c1})"

    def test_estimate_veo3_highest(self, auth_client):
        results = {}
        for eng in ("flux", "kling", "veo3", "pika"):
            r = auth_client.post(f"{API}/studio/render/estimate", json=_estimate_payload(eng), timeout=15).json()
            results[eng] = r.get("estimated_cost_cents") if isinstance(r, dict) else r
        assert results["veo3"] > results["kling"] > results["pika"] > results["flux"], results


# --- Both-aspects endpoint (with immediate cleanup) ----------------------
class TestBothAspects:
    """Fires /studio/render/both-aspects with a MINIMAL pexels payload, then
    IMMEDIATELY bulk-deletes both jobs (admin force-delete) to keep real fal.ai
    + Kokoro charges to a minimum. We verify only the response shape — actual
    render completion is NOT awaited."""

    def test_both_aspects_returns_two_queued_jobs(self, auth_client):
        payload = {
            "mode": "faceless",
            "script": "Test.",  # tiny script, minimal TTS spend
            "aspect": "9_16",  # ignored — endpoint generates both
            "ai_engine": "flux",
            "broll_source": "pexels",  # FREE stock — no fal.ai t2v charges
            "scenes": [{"source": "pexels", "prompt": "ocean"}],
        }
        job_ids = []
        try:
            r = auth_client.post(f"{API}/studio/render/both-aspects", json=payload, timeout=30)
            assert r.status_code == 200, f"{r.status_code} {r.text}"
            body = r.json()
            assert "jobs" in body, f"Missing jobs: {body}"
            jobs = body["jobs"]
            assert isinstance(jobs, list) and len(jobs) == 2, f"Expected 2 jobs, got {jobs}"

            aspects = {j["aspect"] for j in jobs}
            assert aspects == {"9_16", "16_9"}, f"Aspects wrong: {aspects}"

            for j in jobs:
                assert j.get("status") == "queued", f"Job not queued: {j}"
                assert "id" in j
                assert j.get("mode") == "faceless"
                assert j.get("ai_engine") == "flux"
                job_ids.append(j["id"])
        finally:
            # CRITICAL: clean up regardless of test outcome to avoid charges.
            if job_ids:
                del_r = auth_client.post(
                    f"{API}/studio/render/bulk-delete",
                    json={"ids": job_ids},
                    timeout=15,
                )
                # Admin → force delete works even on queued/in-progress
                assert del_r.status_code == 200, f"Cleanup FAILED — manual cleanup may be needed for {job_ids}: {del_r.text}"
                deleted = del_r.json().get("deleted", 0)
                print(f"[cleanup] Deleted {deleted}/{len(job_ids)} jobs: {job_ids}")
