"""F2F48 Studio backend tests."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://3efffc74-5bf3-4c96-8d1a-850f2439f9f2.preview.emergentagent.com").rstrip("/")
BYPASS_EMAIL = "drcharitycampbell@gmail.com"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": BYPASS_EMAIL}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Health ---
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("dry_run") is True


# --- Auth ---
def test_auth_check_bypass():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": BYPASS_EMAIL}, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["user"]["email"] == BYPASS_EMAIL
    assert set(j["user"]["entitlements"]) >= {"base", "shorts", "studio"}
    assert isinstance(j["token"], str) and len(j["token"]) > 10


def test_auth_check_non_bypass_returns_401():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": "random_unknown_user_xyz@example.com"}, timeout=15)
    assert r.status_code == 401


def test_auth_me_with_token(auth_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["email"] == BYPASS_EMAIL
    assert "studio" in j["entitlements"]


def test_auth_me_without_token():
    r = requests.get(f"{BASE_URL}/api/auth/me", timeout=10)
    assert r.status_code == 401


# --- Studio: avatars/voices ---
def test_studio_avatars(auth_headers):
    r = requests.get(f"{BASE_URL}/api/studio/avatars", headers=auth_headers, timeout=60)
    assert r.status_code == 200, r.text
    avatars = r.json()["avatars"]
    assert len(avatars) > 0
    a = avatars[0]
    for k in ("id", "name", "preview_image_url", "gender"):
        assert k in a


def test_studio_voices(auth_headers):
    r = requests.get(f"{BASE_URL}/api/studio/voices", headers=auth_headers, timeout=60)
    assert r.status_code == 200, r.text
    voices = r.json()["voices"]
    assert len(voices) > 0
    v = voices[0]
    for k in ("id", "name", "gender", "language"):
        assert k in v


def test_studio_tts_voices(auth_headers):
    r = requests.get(f"{BASE_URL}/api/studio/tts-voices", headers=auth_headers, timeout=15)
    assert r.status_code == 200
    voices = r.json()["voices"]
    assert len(voices) == 10
    assert all("id" in v and "name" in v and "gender" in v and "language" in v for v in voices)


# --- Stock search ---
def test_stock_search_pexels(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/studio/stock-search",
        params={"source": "pexels", "q": "sunrise", "orientation": "portrait"},
        headers=auth_headers,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert isinstance(results, list)
    if results:
        for k in ("video_url", "thumb", "duration"):
            assert k in results[0]


def test_stock_search_pixabay(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/studio/stock-search",
        params={"source": "pixabay", "q": "mountains", "orientation": "portrait"},
        headers=auth_headers,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert isinstance(results, list)


# --- Render flow ---
@pytest.fixture(scope="session")
def render_job(auth_headers):
    body = {
        "mode": "faceless",
        "script": "Welcome to our story. This is the first scene about sunrise.",
        "aspect": "9_16",
        "captions": True,
        "tts_voice_id": "af_bella",
        "broll_source": "pexels",
        "scenes": [{"source": "pexels", "prompt": "sunrise", "video_url": None, "thumb": None}],
    }
    r = requests.post(f"{BASE_URL}/api/studio/render", json=body, headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "queued"
    assert j["progress"] == 5
    return j


def test_render_creates_job(render_job):
    assert "id" in render_job


def test_render_in_progress_delete_returns_409(auth_headers, render_job):
    # Immediately try to delete while queued/in-progress
    r = requests.delete(f"{BASE_URL}/api/studio/render/{render_job['id']}", headers=auth_headers, timeout=10)
    assert r.status_code == 409


def test_render_progresses_to_complete(auth_headers, render_job):
    job_id = render_job["id"]
    statuses = []
    final = None
    for _ in range(15):  # up to ~15s
        time.sleep(1.2)
        r = requests.get(f"{BASE_URL}/api/studio/render/{job_id}", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        j = r.json()
        statuses.append(j["status"])
        if j["status"] in ("complete", "failed"):
            final = j
            break
    assert final is not None, f"Did not finish in time. Statuses: {statuses}"
    assert final["status"] == "complete", f"final={final}"
    assert final["progress"] == 100
    assert final["result_url"] is not None


def test_history_contains_render(auth_headers, render_job):
    r = requests.get(f"{BASE_URL}/api/studio/history", headers=auth_headers, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["id"] == render_job["id"] for it in items)


def test_delete_completed_render(auth_headers, render_job):
    job_id = render_job["id"]
    r = requests.delete(f"{BASE_URL}/api/studio/render/{job_id}", headers=auth_headers, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # Verify gone from history
    r2 = requests.get(f"{BASE_URL}/api/studio/history", headers=auth_headers, timeout=10)
    assert all(it["id"] != job_id for it in r2.json()["items"])
