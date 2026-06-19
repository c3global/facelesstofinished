"""Iteration 18 — Script Engine new feature tests:

1. POST /api/scripts/long supports include_hooks / include_broll /
   include_production_notes toggles (default True). When set to False the
   generated text should NOT contain the corresponding section headers.
2. Streaming/drip rendering: /api/scripts/job/{id} should expose partially
   accumulated text while status='running' (text field grows over time)
   before flipping to status='complete'.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
BYPASS_EMAIL = "drcharitycampbell@gmail.com"

# Section headers from prompts.py
HOOK_HDR = "HOOK VARIATIONS"
BROLL_HDR = "B-ROLL SHOT LIST"
PROD_HDR = "PRODUCTION NOTES"


@pytest.fixture(scope="module")
def auth_headers():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": BYPASS_EMAIL}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _poll_until_done(headers, sid, timeout=240):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/api/scripts/job/{sid}", headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("complete", "failed"):
            return last
        time.sleep(2)
    raise AssertionError(f"Job did not finish in {timeout}s; last status={last and last.get('status')}")


# ---------------------------------------------------------------------------
# Toggle tests
# ---------------------------------------------------------------------------

def test_long_script_with_all_toggles_off_omits_sections(auth_headers):
    """include_hooks=false, include_broll=false, include_production_notes=false
    -> generated text must NOT contain those three section headers."""
    body = {
        "topic": "faceless youtube income",
        "length": "short",  # short to minimise token spend
        "chosen_angle": {
            "name": "Quiet earnings",
            "framing": "How a faceless creator banks $500/day without showing their face",
            "category": "curiosity",
        },
        "include_hooks": False,
        "include_broll": False,
        "include_production_notes": False,
    }
    r = requests.post(f"{BASE_URL}/api/scripts/long", json=body, headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json()["status"] == "running"
    final = _poll_until_done(auth_headers, sid)
    assert final["status"] == "complete", f"Job failed: {final.get('error')}"
    text = final.get("text") or ""
    assert HOOK_HDR not in text, f"HOOK VARIATIONS present when toggled OFF; text head: {text[:400]}"
    assert BROLL_HDR not in text, "B-ROLL SHOT LIST present when toggled OFF"
    assert PROD_HDR not in text, "PRODUCTION NOTES present when toggled OFF"
    # Should still contain the mandatory sections
    assert "VIDEO CONCEPT" in text
    assert "FULL NARRATION SCRIPT" in text


def test_long_script_with_all_toggles_on_includes_sections(auth_headers):
    """All toggles ON (default) -> all three sections must be present."""
    body = {
        "topic": "ai side hustles for 2026",
        "length": "short",
        "chosen_angle": {
            "name": "Underrated AI workflows",
            "framing": "Three AI workflows nobody is talking about yet",
            "category": "list",
        },
        "include_hooks": True,
        "include_broll": True,
        "include_production_notes": True,
    }
    r = requests.post(f"{BASE_URL}/api/scripts/long", json=body, headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    final = _poll_until_done(auth_headers, sid)
    assert final["status"] == "complete", f"Job failed: {final.get('error')}"
    text = final.get("text") or ""
    assert HOOK_HDR in text, f"HOOK VARIATIONS missing; head: {text[:400]}"
    assert BROLL_HDR in text, "B-ROLL SHOT LIST missing"
    assert PROD_HDR in text, "PRODUCTION NOTES missing"


# ---------------------------------------------------------------------------
# Streaming / drip tests
# ---------------------------------------------------------------------------

def test_long_script_streams_partial_text(auth_headers):
    """During generation /scripts/job/{id} should expose a growing `text`
    field while status='running' (drip rendering)."""
    body = {
        "topic": "passive income youtube channels",
        "length": "short",
        "chosen_angle": {
            "name": "Set and forget",
            "framing": "Channels that earn while the creator sleeps",
            "category": "curiosity",
        },
    }
    r = requests.post(f"{BASE_URL}/api/scripts/long", json=body, headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    samples = []  # list of (status, text_len)
    deadline = time.time() + 180
    while time.time() < deadline:
        jr = requests.get(f"{BASE_URL}/api/scripts/job/{sid}", headers=auth_headers, timeout=20)
        assert jr.status_code == 200
        j = jr.json()
        samples.append((j["status"], len(j.get("text") or "")))
        if j["status"] in ("complete", "failed"):
            break
        time.sleep(0.5)

    # We need to have seen at least one 'running' state with non-empty text
    running_with_text = [s for s in samples if s[0] == "running" and s[1] > 0]
    final = samples[-1]
    assert final[0] == "complete", f"Job not complete: {final}; samples={samples[:10]}"

    # Verify text grew (streaming) — at least one running snapshot had text
    # OR the lengths in running snapshots were non-decreasing and not all zero.
    text_lens = [s[1] for s in samples if s[0] == "running"]
    print(f"Streaming samples: status seq={[s[0] for s in samples][:20]}, running text lens={text_lens[:20]}, final_len={final[1]}")
    assert running_with_text, (
        f"No partial text emitted during streaming — drip rendering broken. "
        f"Running snapshots had only empty text. samples={samples[:20]}"
    )
    # Monotonic-ish growth check
    if len(text_lens) >= 2:
        assert text_lens[-1] >= text_lens[0], "Text length decreased during streaming"
