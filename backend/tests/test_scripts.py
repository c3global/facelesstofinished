"""F2F48 Script Engine + Studio broll-prompts tests (iteration 4).

NEW (it4): /api/scripts/{long,shorts,repurpose} returns immediately with
{id, status:'running'}. Client polls GET /api/scripts/job/{id} every few
seconds until status in {complete, failed}.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
BYPASS_EMAIL = "drcharitycampbell@gmail.com"

POLL_INTERVAL_SEC = 3
POLL_TIMEOUT_SEC = 180


@pytest.fixture(scope="module")
def auth_headers():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": BYPASS_EMAIL}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _poll_job(headers, script_id, timeout=POLL_TIMEOUT_SEC):
    """Poll GET /api/scripts/job/{id} until terminal status or timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/scripts/job/{script_id}", headers=headers, timeout=20)
        assert r.status_code == 200, f"Polling failed: {r.status_code} {r.text}"
        last = r.json()
        if last["status"] in ("complete", "failed"):
            return last
        time.sleep(POLL_INTERVAL_SEC)
    raise AssertionError(f"Polling timed out after {timeout}s, last status: {last and last.get('status')}")


# --- /api/studio/broll-prompts ---
def test_broll_prompts_requires_auth():
    r = requests.post(f"{BASE_URL}/api/studio/broll-prompts", json={"script": "x"}, timeout=10)
    assert r.status_code == 401


def test_broll_prompts_empty_script_400(auth_headers):
    r = requests.post(f"{BASE_URL}/api/studio/broll-prompts", json={"script": "   "}, headers=auth_headers, timeout=30)
    assert r.status_code == 400


def test_broll_prompts_success(auth_headers):
    script = (
        "The sun rises over a quiet desert highway. A lone traveler pours coffee from a thermos. "
        "He looks at a worn paper map. The wind kicks up dust. He smiles, gets back in the truck, and drives east."
    )
    r = requests.post(
        f"{BASE_URL}/api/studio/broll-prompts",
        json={"script": script},
        headers=auth_headers,
        timeout=60,
    )
    assert r.status_code == 200, r.text
    prompts = r.json()["prompts"]
    assert isinstance(prompts, list)
    assert 4 <= len(prompts) <= 12, f"Got {len(prompts)} prompts"
    for p in prompts:
        assert not p.startswith(("-", "*", "•", '"')), f"Bad prefix: {p!r}"
        assert not p[:2].rstrip(".").isdigit(), f"Bad numeric prefix: {p!r}"
        assert len(p) < 200


# --- /api/scripts/long (async-job) ---
LONG_SECTIONS = [
    "TOPIC ANGLES",
    "VIDEO CONCEPT",
    "HOOK VARIATIONS",
    "OUTLINE",
    "FULL NARRATION SCRIPT",
    "TRANSITIONS",
    "B-ROLL SHOT LIST",
    "PRODUCTION NOTES",
]


@pytest.fixture(scope="module")
def long_script(auth_headers):
    body = {"topic": "How to find your first faceless niche in 24 hours", "length": "short"}
    t0 = time.time()
    r = requests.post(
        f"{BASE_URL}/api/scripts/long",
        json=body,
        headers=auth_headers,
        timeout=15,
    )
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    # POST must return fast (well under 60s edge timeout) with running status
    assert elapsed < 10, f"POST took {elapsed:.1f}s — should be <1s for async pattern"
    assert j["status"] == "running", f"Expected running, got {j['status']}"
    assert j["mode"] == "long"
    assert j["topic"] == body["topic"]
    assert isinstance(j["id"], str) and len(j["id"]) >= 8
    assert j.get("text") is None
    # Poll until complete
    done = _poll_job(auth_headers, j["id"], timeout=180)
    assert done["status"] == "complete", f"Job failed: {done.get('error')}"
    return done


def test_scripts_long_post_returns_running(long_script):
    # Validated via fixture assertions
    assert long_script["status"] == "complete"
    assert long_script["mode"] == "long"


def test_scripts_long_structure(long_script):
    assert long_script["length"] == "short"
    text = long_script["text"]
    assert isinstance(text, str) and len(text) > 200
    for hdr in LONG_SECTIONS:
        assert hdr in text, f"Missing section: {hdr}"


def test_scripts_long_invalid_length(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/scripts/long",
        json={"topic": "anything", "length": "huge"},
        headers=auth_headers,
        timeout=15,
    )
    assert r.status_code == 400


def test_scripts_long_empty_topic(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/scripts/long",
        json={"topic": "  ", "length": "short"},
        headers=auth_headers,
        timeout=15,
    )
    assert r.status_code == 400


# --- /api/scripts/shorts (async-job) ---
SHORTS_SECTIONS = [
    "HOOK VARIATIONS",
    "SHORT-FORM SCRIPT",
    "ON-SCREEN TEXT",
    "B-ROLL SHOT LIST",
    "CAPTION",
    "HASHTAGS",
    "TITLE / THUMBNAIL VARIANTS",
    "COVER IMAGE PROMPTS",
    "PRODUCTION NOTES",
]


@pytest.fixture(scope="module")
def shorts_script(auth_headers):
    t0 = time.time()
    r = requests.post(
        f"{BASE_URL}/api/scripts/shorts",
        json={"topic": "Stop scrolling before bed", "platform": "youtube"},
        headers=auth_headers,
        timeout=15,
    )
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert elapsed < 10
    assert j["status"] == "running"
    assert j["mode"] == "shorts"
    done = _poll_job(auth_headers, j["id"], timeout=180)
    assert done["status"] == "complete", f"Shorts job failed: {done.get('error')}"
    return done


def test_scripts_shorts_structure(shorts_script):
    assert shorts_script["platform"] == "youtube"
    text = shorts_script["text"]
    for hdr in SHORTS_SECTIONS:
        assert hdr in text, f"Missing section: {hdr}"


def test_scripts_shorts_invalid_platform(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/scripts/shorts",
        json={"topic": "x", "platform": "snapchat"},
        headers=auth_headers,
        timeout=15,
    )
    assert r.status_code == 400


# --- /api/scripts/repurpose (async-job) ---
@pytest.fixture(scope="module")
def repurposed_script(auth_headers, long_script):
    t0 = time.time()
    r = requests.post(
        f"{BASE_URL}/api/scripts/repurpose",
        json={"source_script": long_script["text"][:4000], "platform": "reels"},
        headers=auth_headers,
        timeout=15,
    )
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert elapsed < 10
    assert j["status"] == "running"
    done = _poll_job(auth_headers, j["id"], timeout=180)
    assert done["status"] == "complete", f"Repurpose job failed: {done.get('error')}"
    return done


def test_scripts_repurpose_returns_shorts(repurposed_script):
    assert repurposed_script["mode"] == "shorts"
    assert repurposed_script["platform"] == "reels"
    assert "SHORT-FORM SCRIPT" in repurposed_script["text"]


def test_scripts_repurpose_empty_source(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/scripts/repurpose",
        json={"source_script": "  ", "platform": "reels"},
        headers=auth_headers,
        timeout=15,
    )
    assert r.status_code == 400


# --- /api/scripts/job/{id} negative paths ---
def test_scripts_job_nonexistent_returns_404(auth_headers):
    r = requests.get(f"{BASE_URL}/api/scripts/job/does-not-exist-1234", headers=auth_headers, timeout=10)
    assert r.status_code == 404


def test_scripts_job_requires_auth(long_script):
    # No Authorization header
    r = requests.get(f"{BASE_URL}/api/scripts/job/{long_script['id']}", timeout=10)
    assert r.status_code == 401


# --- /api/scripts/history + get + delete ---
def test_scripts_history_contains_all(auth_headers, long_script, shorts_script, repurposed_script):
    r = requests.get(f"{BASE_URL}/api/scripts/history", headers=auth_headers, timeout=15)
    assert r.status_code == 200
    items = r.json()["items"]
    ids = {it["id"] for it in items}
    assert long_script["id"] in ids
    assert shorts_script["id"] in ids
    assert repurposed_script["id"] in ids
    # descending order check
    created_dates = [it["created_at"] for it in items]
    assert created_dates == sorted(created_dates, reverse=True)


def test_scripts_get_by_id(auth_headers, long_script):
    r = requests.get(f"{BASE_URL}/api/scripts/{long_script['id']}", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    assert r.json()["id"] == long_script["id"]


def test_scripts_delete_and_verify(auth_headers, repurposed_script):
    sid = repurposed_script["id"]
    r = requests.delete(f"{BASE_URL}/api/scripts/{sid}", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    r2 = requests.get(f"{BASE_URL}/api/scripts/{sid}", headers=auth_headers, timeout=10)
    assert r2.status_code == 404


def test_scripts_delete_missing_404(auth_headers):
    r = requests.delete(f"{BASE_URL}/api/scripts/does-not-exist", headers=auth_headers, timeout=10)
    assert r.status_code == 404


# --- auth gating ---
def test_scripts_long_unauthenticated_returns_401():
    r = requests.post(f"{BASE_URL}/api/scripts/long", json={"topic": "x", "length": "short"}, timeout=10)
    assert r.status_code == 401
