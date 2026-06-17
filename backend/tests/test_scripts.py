"""F2F48 Script Engine + Studio broll-prompts tests (iteration 7).

Iter-7 changes covered here:
* NEW /api/scripts/angles (sync, fast) — returns 4 angles for a topic.
* /api/scripts/long + /api/scripts/shorts now accept chosen_angle dict and the
  result text should NOT include a "TOPIC ANGLES" section.
* NEW /api/scripts/saved-angles CRUD.
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
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/scripts/job/{script_id}", headers=headers, timeout=20)
        assert r.status_code == 200, f"Polling failed: {r.status_code} {r.text}"
        last = r.json()
        if last["status"] in ("complete", "failed"):
            return last
        time.sleep(POLL_INTERVAL_SEC)
    raise AssertionError(f"Polling timed out after {timeout}s, last: {last and last.get('status')}")


# --- /api/studio/broll-prompts (regression) ---
def test_broll_prompts_requires_auth():
    r = requests.post(f"{BASE_URL}/api/studio/broll-prompts", json={"script": "x"}, timeout=10)
    assert r.status_code == 401


def test_broll_prompts_empty_script_400(auth_headers):
    r = requests.post(f"{BASE_URL}/api/studio/broll-prompts", json={"script": "   "}, headers=auth_headers, timeout=30)
    assert r.status_code == 400


# --- /api/scripts/angles (NEW iter7) ---
ANGLE_CATEGORIES = {"curiosity", "contrarian", "how-to", "story", "list"}


@pytest.fixture(scope="module")
def angles_response(auth_headers):
    t0 = time.time()
    r = requests.post(
        f"{BASE_URL}/api/scripts/angles",
        json={"topic": "How to find your first faceless niche in 24 hours"},
        headers=auth_headers,
        timeout=30,
    )
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 25, f"angles call took {elapsed:.1f}s, should be <15s ideally"
    return r.json()


def test_angles_shape(angles_response):
    assert angles_response["topic"]
    angles = angles_response["angles"]
    assert isinstance(angles, list)
    assert 4 <= len(angles) <= 5, f"Expected ~5 angles, got {len(angles)}"
    for a in angles:
        assert a["name"] and isinstance(a["name"], str)
        assert a["framing"] and isinstance(a["framing"], str)
        assert a["category"] in ANGLE_CATEGORIES


def test_angles_empty_topic_400(auth_headers):
    r = requests.post(f"{BASE_URL}/api/scripts/angles", json={"topic": "  "}, headers=auth_headers, timeout=15)
    assert r.status_code == 400


def test_angles_requires_auth():
    r = requests.post(f"{BASE_URL}/api/scripts/angles", json={"topic": "x"}, timeout=10)
    assert r.status_code == 401


# --- /api/scripts/saved-angles CRUD (NEW iter7) ---
@pytest.fixture(scope="module")
def saved_angle_ids(auth_headers):
    created = []
    for i in range(3):
        body = {
            "topic": f"TEST_topic_{i}",
            "angle": {"name": f"TEST angle {i}", "framing": f"framing {i}", "category": "curiosity"},
        }
        r = requests.post(f"{BASE_URL}/api/scripts/saved-angles", json=body, headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["id"] and j["user_email"] and j["created_at"]
        assert j["topic"] == body["topic"]
        assert j["angle"]["name"] == body["angle"]["name"]
        created.append(j["id"])
    yield created
    # cleanup
    for sid in created:
        requests.delete(f"{BASE_URL}/api/scripts/saved-angles/{sid}", headers=auth_headers, timeout=10)


def test_saved_angles_list_contains_created(auth_headers, saved_angle_ids):
    r = requests.get(f"{BASE_URL}/api/scripts/saved-angles", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    ids = {i["id"] for i in items}
    for sid in saved_angle_ids:
        assert sid in ids
    # newest first
    dates = [i["created_at"] for i in items]
    assert dates == sorted(dates, reverse=True)


def test_saved_angles_delete_and_verify(auth_headers, saved_angle_ids):
    target = saved_angle_ids[0]
    r = requests.delete(f"{BASE_URL}/api/scripts/saved-angles/{target}", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/scripts/saved-angles", headers=auth_headers, timeout=10)
    ids = {i["id"] for i in r2.json()["items"]}
    assert target not in ids


def test_saved_angles_delete_missing_404(auth_headers):
    r = requests.delete(f"{BASE_URL}/api/scripts/saved-angles/does-not-exist", headers=auth_headers, timeout=10)
    assert r.status_code == 404


def test_saved_angles_invalid_payload_400(auth_headers):
    r = requests.post(f"{BASE_URL}/api/scripts/saved-angles", json={"topic": "x", "angle": {}}, headers=auth_headers, timeout=10)
    assert r.status_code == 400


def test_saved_angles_requires_auth():
    r = requests.get(f"{BASE_URL}/api/scripts/saved-angles", timeout=10)
    assert r.status_code == 401


# --- /api/scripts/long with chosen_angle (iter7) ---
# Iter7: TOPIC ANGLES is REMOVED from long output (step 2 system prompt skips angles).
LONG_SECTIONS = [
    "VIDEO CONCEPT",
    "HOOK VARIATIONS",
    "OUTLINE",
    "FULL NARRATION SCRIPT",
    "TRANSITIONS",
    "B-ROLL SHOT LIST",
    "PRODUCTION NOTES",
]


@pytest.fixture(scope="module")
def long_script_with_angle(auth_headers, angles_response):
    chosen = angles_response["angles"][0]
    body = {
        "topic": angles_response["topic"],
        "length": "short",
        "chosen_angle": chosen,
    }
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/api/scripts/long", json=body, headers=auth_headers, timeout=15)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert elapsed < 10
    assert j["status"] == "running"
    # chosen_angle must be persisted on the record
    assert j["chosen_angle"]["name"] == chosen["name"]
    assert j["chosen_angle"]["framing"] == chosen["framing"]
    done = _poll_job(auth_headers, j["id"], timeout=180)
    assert done["status"] == "complete", f"Job failed: {done.get('error')}"
    return done


def test_long_persists_chosen_angle(long_script_with_angle, angles_response):
    chosen = angles_response["angles"][0]
    assert long_script_with_angle["chosen_angle"]["name"] == chosen["name"]
    assert long_script_with_angle["chosen_angle"]["framing"] == chosen["framing"]


def test_long_text_has_sections_and_no_topic_angles(long_script_with_angle):
    text = long_script_with_angle["text"]
    assert isinstance(text, str) and len(text) > 200
    for hdr in LONG_SECTIONS:
        assert hdr in text, f"Missing section header: {hdr}"
    # Iter7: TOPIC ANGLES must NOT appear in the output
    assert "TOPIC ANGLES" not in text, "TOPIC ANGLES section should be removed in iter7"


def test_long_invalid_length(auth_headers):
    r = requests.post(f"{BASE_URL}/api/scripts/long", json={"topic": "x", "length": "huge"}, headers=auth_headers, timeout=15)
    assert r.status_code == 400


def test_long_empty_topic(auth_headers):
    r = requests.post(f"{BASE_URL}/api/scripts/long", json={"topic": "  ", "length": "short"}, headers=auth_headers, timeout=15)
    assert r.status_code == 400


def test_long_unauthenticated_returns_401():
    r = requests.post(f"{BASE_URL}/api/scripts/long", json={"topic": "x", "length": "short"}, timeout=10)
    assert r.status_code == 401


# --- /api/scripts/shorts with chosen_angle + platform=tiktok (iter7) ---
@pytest.fixture(scope="module")
def shorts_tiktok_with_angle(auth_headers, angles_response):
    chosen = angles_response["angles"][0]
    body = {
        "topic": angles_response["topic"],
        "platform": "tiktok",
        "chosen_angle": chosen,
    }
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/api/scripts/shorts", json=body, headers=auth_headers, timeout=15)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert elapsed < 10
    assert j["status"] == "running"
    assert j["platform"] == "tiktok"
    assert j["chosen_angle"]["name"] == chosen["name"]
    done = _poll_job(auth_headers, j["id"], timeout=180)
    assert done["status"] == "complete", f"Shorts job failed: {done.get('error')}"
    return done


def test_shorts_text_has_headers_and_no_topic_angles(shorts_tiktok_with_angle):
    text = shorts_tiktok_with_angle["text"]
    assert "### 📱 SHORT-FORM SCRIPT" in text, "Missing short-form script header"
    # Beat markers
    assert "[HOOK" in text or "[HOOK]" in text
    assert "[BODY" in text or "[BODY]" in text
    assert "[CTA" in text or "[CTA]" in text
    # No TOPIC ANGLES section
    assert "TOPIC ANGLES" not in text


def test_shorts_invalid_platform(auth_headers):
    r = requests.post(f"{BASE_URL}/api/scripts/shorts", json={"topic": "x", "platform": "snapchat"}, headers=auth_headers, timeout=15)
    assert r.status_code == 400


# --- job/{id} negative paths ---
def test_scripts_job_nonexistent_returns_404(auth_headers):
    r = requests.get(f"{BASE_URL}/api/scripts/job/does-not-exist-1234", headers=auth_headers, timeout=10)
    assert r.status_code == 404


def test_scripts_job_requires_auth(long_script_with_angle):
    r = requests.get(f"{BASE_URL}/api/scripts/job/{long_script_with_angle['id']}", timeout=10)
    assert r.status_code == 401


# --- history + get + delete ---
def test_scripts_history_contains_jobs(auth_headers, long_script_with_angle, shorts_tiktok_with_angle):
    r = requests.get(f"{BASE_URL}/api/scripts/history", headers=auth_headers, timeout=15)
    assert r.status_code == 200
    ids = {it["id"] for it in r.json()["items"]}
    assert long_script_with_angle["id"] in ids
    assert shorts_tiktok_with_angle["id"] in ids


def test_scripts_delete_and_verify(auth_headers, shorts_tiktok_with_angle):
    sid = shorts_tiktok_with_angle["id"]
    r = requests.delete(f"{BASE_URL}/api/scripts/{sid}", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/scripts/{sid}", headers=auth_headers, timeout=10)
    assert r2.status_code == 404
