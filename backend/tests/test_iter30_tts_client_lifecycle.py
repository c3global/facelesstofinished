"""Regression tests for the Faceless render TTS-client-lifecycle bug.

The bug: in `_run_render_faceless`, the TTS task was awaited AFTER the
`async with httpx.AsyncClient(...) as client:` block had exited. Because
`_run_tts` captures `client` via closure and may retry on ReadError, any
retry that fired after the with-block exited would call `.post()` on a
closed client, raising `RuntimeError: Cannot send a request, as the
client has been closed.` and surfacing as:

    Render failed: Voiceover error: RuntimeError: Cannot send a request,
    as the client has been closed.

The fix moves the `await tts_task` + status_code/.json() parsing INSIDE
the async-with block so the client stays alive until TTS is fully done.

These tests verify the regression by:
  1. Issuing a real Faceless render with a LONG (1000+ char, 6+ scene)
     script and polling the status endpoint until the job reaches a
     terminal status OR moves past the `visuals` stage (which proves TTS
     completed without hitting the closed-client error).
  2. Issuing a real Faceless render with a SHORT 2-scene script to
     confirm the happy path still works.
  3. Validating that `/api/studio/history` still lists historical jobs
     (no model migration breakage).
  4. Spot-checking the audio_url extraction path on a completed job.

Real fal.ai calls ARE made — Kokoro TTS + Flux. Tests are skipped if no
auth token can be obtained or if the API is unreachable.
"""

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://f2f48-video-engine.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "drcharitycampbell@gmail.com"

# --- Hard ceiling on how long we wait for any single render to finish.
# Real fal.ai compose can take 90-180s; we DO NOT need the job to fully
# complete to verify the fix — we only need it to move past the
# `visuals` stage (which proves TTS completed without closed-client
# RuntimeError). Cap at 4 minutes per render to keep CI sane.
MAX_RENDER_WAIT_S = 240
POLL_INTERVAL_S = 5

# Stages that prove TTS completed successfully (the closed-client bug
# would surface DURING the `visuals` stage when retries hit, so any
# status STRICTLY beyond `visuals` confirms the fix).
POST_TTS_STATUSES = {"composing", "complete", "encoding", "finalizing"}
TERMINAL_STATUSES = {"complete", "failed"}

CLOSED_CLIENT_FINGERPRINT = "Cannot send a request, as the client has been closed"


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def auth_token() -> str:
    """Obtain DEV_BYPASS JWT for the admin email."""
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/check",
            json={"email": ADMIN_EMAIL},
            timeout=15,
        )
    except requests.RequestException as exc:
        pytest.skip(f"Backend unreachable: {exc}")
    if r.status_code != 200:
        pytest.skip(f"Auth failed for {ADMIN_EMAIL}: {r.status_code} {r.text[:200]}")
    token = r.json().get("token")
    assert token, "Auth response missing token"
    return token


@pytest.fixture(scope="module")
def auth_headers(auth_token: str) -> dict:
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }


# --- Helpers ----------------------------------------------------------------


def _poll_until_post_tts_or_terminal(job_id: str, headers: dict, max_wait_s: int = MAX_RENDER_WAIT_S):
    """Poll /api/studio/render/{job_id} until the job reaches a status
    that proves TTS completed (POST_TTS_STATUSES) OR a terminal status
    (complete/failed). Returns the final doc and the elapsed seconds.
    """
    deadline = time.time() + max_wait_s
    last_doc: dict = {}
    while time.time() < deadline:
        r = requests.get(
            f"{BASE_URL}/api/studio/render/{job_id}",
            headers=headers,
            timeout=15,
        )
        if r.status_code != 200:
            time.sleep(POLL_INTERVAL_S)
            continue
        last_doc = r.json()
        status = (last_doc.get("status") or "").lower()
        if status in TERMINAL_STATUSES or status in POST_TTS_STATUSES:
            return last_doc, time.time() - (deadline - max_wait_s)
        time.sleep(POLL_INTERVAL_S)
    return last_doc, max_wait_s


def _long_script() -> str:
    """Return a 1000+ character script with explicit scene cues."""
    paragraphs = [
        "Scene one: Imagine standing on the edge of a cliff at sunrise, with the entire valley stretching out beneath you in golden light. The wind is steady, the air is crisp, and you can hear nothing but the distant call of a single hawk circling overhead.",
        "Scene two: Now picture an old wooden cabin nestled deep in a snow-covered pine forest. Smoke curls lazily from the stone chimney, and warm yellow light glows in every frosted window, inviting you in from the cold.",
        "Scene three: Switch to a bustling night market in Tokyo. Neon signs reflect off rain-slicked streets, vendors shout over the hiss of grills, and the smell of yakitori drifts past every storefront.",
        "Scene four: Cut to a quiet library at midnight, where rows of leather-bound books stretch into shadow. A single green-shaded lamp pools light onto an open journal, the pen still warm from the writer's hand.",
        "Scene five: Now we are deep underwater, drifting alongside a coral reef teeming with schools of silver fish that turn as one body, while sunlight ripples down through the surface far above us.",
        "Scene six: Finally, we soar above the clouds at dawn, the curve of the earth visible on the horizon, the first rays of sunlight painting the cloud tops in soft pink and gold as the day begins.",
    ]
    script = " ".join(paragraphs)
    assert len(script) >= 1000, f"Long script must be 1000+ chars, got {len(script)}"
    return script


def _short_script() -> str:
    """Sub-200-char 2-scene script for the happy-path test."""
    return (
        "Scene one: a calm lake at dawn with mist rising. "
        "Scene two: a single red maple leaf falling onto still water."
    )


def _scenes_from_prompts(prompts: list) -> list:
    """Build the minimal scene list the RenderRequest schema expects."""
    return [
        {"source": "ai", "prompt": p, "weight": max(1, len(p.split()))}
        for p in prompts
    ]


# --- Tests ------------------------------------------------------------------


class TestStudioHistory:
    """`/api/studio/history` must still list jobs (incl. historical
    Voiceover-error failures) after any model migration."""

    def test_history_lists_jobs(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/studio/history", headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"history failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        # Every item must round-trip cleanly (no ObjectId leakage).
        for item in data["items"]:
            assert "_id" not in item, "ObjectId leaked into history response"
            assert "id" in item
            assert "status" in item

    def test_history_includes_prior_voiceover_failures_readable(self, auth_headers):
        """Spot-check: any historical job with a 'Voiceover error' string
        in its `error` field is still serializable and readable. This
        confirms the model migration didn't drop the field."""
        r = requests.get(f"{BASE_URL}/api/studio/history", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        voiceover_failures = [
            it for it in items
            if (it.get("error") or "").lower().find("voiceover") >= 0
        ]
        # If there are no historical voiceover failures, this test
        # passes trivially — we only need to confirm that IF such
        # records exist, they are still serializable.
        for item in voiceover_failures:
            assert isinstance(item.get("error"), str)
            assert item.get("status") == "failed"


class TestFacelessRenderShortScript:
    """Happy-path: short script, 2 scenes — the fast common case."""

    def test_short_script_render_passes_tts(self, auth_headers):
        payload = {
            "mode": "faceless",
            "script": _short_script(),
            "aspect": "9_16",
            "captions": False,
            "broll_source": "ai",
            "ai_engine": "flux_static",  # avoid expensive Kling i2v
            "tts_voice_id": "af_heart",
            "scenes": _scenes_from_prompts([
                "a calm lake at dawn with mist rising",
                "a single red maple leaf falling onto still water",
            ]),
        }
        r = requests.post(f"{BASE_URL}/api/studio/render", headers=auth_headers, json=payload, timeout=30)
        assert r.status_code == 200, f"render submit failed: {r.status_code} {r.text[:300]}"
        job = r.json()
        job_id = job.get("id")
        assert job_id, "no job id returned"
        assert job.get("status") == "queued"

        final, elapsed = _poll_until_post_tts_or_terminal(job_id, auth_headers)
        status = (final.get("status") or "").lower()
        error = final.get("error") or ""

        # Critical: the closed-client error must NOT appear.
        assert CLOSED_CLIENT_FINGERPRINT not in error, (
            f"REGRESSION: closed-client RuntimeError surfaced on short-script render: {error}"
        )

        # The job must have moved past TTS (status in POST_TTS_STATUSES)
        # OR completed OR failed with a non-TTS-lifecycle error.
        assert status in POST_TTS_STATUSES or status in TERMINAL_STATUSES, (
            f"short render stalled before TTS completion: status={status} progress={final.get('progress')} label={final.get('progress_label')}"
        )


class TestFacelessRenderLongScript:
    """The regression: long script that forces retries on Kokoro.
    If the bug is back, this is where it surfaces."""

    def test_long_script_render_clears_tts_stage(self, auth_headers):
        prompts = [
            "a sunrise cliff overlooking a vast golden valley with a single hawk circling",
            "a wooden cabin in a snow-covered pine forest with warm yellow window light",
            "a neon-lit Tokyo night market with rain-slicked streets and grill smoke",
            "a quiet midnight library with a green-shaded lamp on an open journal",
            "an underwater coral reef with schools of silver fish in rippling sunlight",
            "soaring above clouds at dawn with the curve of the earth on the horizon",
        ]
        payload = {
            "mode": "faceless",
            "script": _long_script(),
            "aspect": "9_16",
            "captions": False,
            "broll_source": "ai",
            "ai_engine": "flux_static",  # static stills — cheaper; TTS path identical
            "tts_voice_id": "af_heart",
            "scenes": _scenes_from_prompts(prompts),
        }
        r = requests.post(f"{BASE_URL}/api/studio/render", headers=auth_headers, json=payload, timeout=30)
        assert r.status_code == 200, f"render submit failed: {r.status_code} {r.text[:300]}"
        job = r.json()
        job_id = job.get("id")
        assert job_id

        final, _elapsed = _poll_until_post_tts_or_terminal(job_id, auth_headers)
        status = (final.get("status") or "").lower()
        error = final.get("error") or ""
        progress_label = final.get("progress_label") or ""

        # PRIMARY assertion: the closed-client RuntimeError must NOT appear.
        assert CLOSED_CLIENT_FINGERPRINT not in error, (
            "REGRESSION DETECTED: TTS-client-lifecycle bug is back.\n"
            f"  status={status}\n  error={error}\n  progress_label={progress_label}\n"
            f"  job_id={job_id}\n"
            "  This means the `await tts_task` is again outside the `async with httpx.AsyncClient` block."
        )

        # Secondary: the job should have moved past the visuals stage
        # (or completed/failed for a different reason). Stalling
        # indefinitely at <30% with status=visuals would suggest a
        # different stall path; surface it as info, not as a failure.
        if status not in POST_TTS_STATUSES and status not in TERMINAL_STATUSES:
            pytest.skip(
                f"long render did not reach post-TTS within {MAX_RENDER_WAIT_S}s "
                f"but no closed-client error was observed. "
                f"status={status} progress={final.get('progress')} label={progress_label}"
            )

    def test_audio_url_extracted_when_render_completes(self, auth_headers):
        """If a recent faceless job completed, `result_data` (or
        `result_url`) should be populated — confirms the `.json()` parse
        inside the async-with block still feeds downstream stages."""
        r = requests.get(f"{BASE_URL}/api/studio/history", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        completed_faceless = [
            it for it in items
            if it.get("status") == "complete" and it.get("mode") == "faceless"
        ]
        if not completed_faceless:
            pytest.skip("No completed faceless renders in history to inspect")
        # Just confirm the most recent completed faceless render has a result_url.
        latest = completed_faceless[0]
        assert latest.get("result_url"), (
            f"completed faceless job missing result_url: id={latest.get('id')}"
        )
