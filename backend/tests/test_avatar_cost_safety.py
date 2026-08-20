"""Regression coverage for the Avatar billing incident on 2026-08-20."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

asyncio.set_event_loop(asyncio.new_event_loop())

import server
from render_privacy import scrub_render_for_customer


def _avatar(script: str) -> server.RenderRequest:
    return server.RenderRequest(
        mode="avatar",
        script=script,
        avatar_id="avatar-test",
        voice_id="voice-test",
    )


def test_three_minute_avatar_is_estimated_and_allowed():
    payload = _avatar("word " * 450)

    assert server._avatar_max_words() == 450
    assert server._estimate_avatar_cost_cents(payload.script) == 300
    assert server.estimate_render_cost_cents(payload) == 300
    server._enforce_avatar_cost_limit(payload)


def test_avatar_cost_limit_cannot_be_bypassed_by_caller_role():
    # The limiter accepts only the payload, not an AuthUser. That makes the
    # same hard ceiling apply to customers, admins, and direct API callers.
    with pytest.raises(HTTPException) as exc:
        server._enforce_avatar_cost_limit(_avatar("word " * 451))

    assert exc.value.status_code == 400
    assert "450 words" in str(exc.value.detail)


def test_provider_character_limit_is_enforced_server_side():
    with pytest.raises(HTTPException):
        server._enforce_avatar_cost_limit(_avatar("x" * 5001))


def test_avatar_generation_is_v2_only_and_idempotent():
    source = inspect.getsource(server._run_render_avatar)

    assert "https://api.heygen.com/v2/video/generate" in source
    assert "/v3/videos" not in source
    assert '"Idempotency-Key": f"f48-avatar-{job_id}"' in source
    assert '"heygen_video_id": video_id' in source


def test_avatar_both_aspects_is_rejected_before_job_creation():
    source = inspect.getsource(server.studio_render_both_aspects)
    avatar_guard = source.index('if payload.mode == "avatar":')
    job_creation = source.index("job_id = str(uuid.uuid4())")

    assert avatar_guard < job_creation
    assert "Rendering both aspects is available for Faceless videos only" in source


def test_customer_render_scrub_hides_avatar_provider_tracking():
    raw = {
        "id": "render-1",
        "status": "avatar",
        "heygen_video_id": "provider-job-secret",
        "heygen_endpoint": "v2-avatar-iii",
        "heygen_submitted_at": "2026-08-20T00:00:00Z",
        "heygen_submit_error": "private provider response",
    }

    assert scrub_render_for_customer(raw) == {"id": "render-1", "status": "avatar"}


def test_studio_ui_warns_at_450_words_and_hides_avatar_dual_aspect():
    studio = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "pages"
        / "Studio.jsx"
    ).read_text()

    assert "const AVATAR_SCRIPT_MAX_WORDS = 450;" in studio
    assert "avatarWordCount > AVATAR_SCRIPT_MAX_WORDS" in studio
    button = studio.index('data-testid="generate-both-aspects-btn"')
    assert "mode === MODES.FACELESS" in studio[button - 300:button]
