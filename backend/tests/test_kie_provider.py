"""Mocked tests for KieProvider — no paid API calls.

Every test uses respx to intercept KIE HTTP traffic. If a test somehow
tries to reach api.kie.ai for real, respx raises so the test fails
loudly instead of billing the account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest
import respx

# Ensure ``backend`` package is importable.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.kie_provider import (  # noqa: E402
    KIE_CREATE_URL,
    KIE_RECORD_URL,
    KieProvider,
)
from providers.types import (  # noqa: E402
    MotionInputMode,
    ProviderStatus,
    SceneMotionRequest,
)


# ---------- fixtures -----------------------------------------------------


@pytest.fixture
def fast_provider(monkeypatch):
    """Provider with polling accelerated so tests finish fast."""
    monkeypatch.setenv("KIE_API_KEY", "test-key-do-not-use")
    monkeypatch.setenv("KIE_POLL_INTERVAL_S", "0.01")
    monkeypatch.setenv("KIE_MAX_WAIT_S", "5.0")
    # Re-read constants by rebuilding the provider
    from importlib import reload
    import providers.kie_provider as kie_mod

    reload(kie_mod)
    return kie_mod.KieProvider(api_key="test-key-do-not-use")


def _text_request(**overrides) -> SceneMotionRequest:
    defaults = dict(
        mode=MotionInputMode.TEXT,
        duration_ms=5000,
        aspect_ratio="16:9",
        resolution="720p",
        prompt="A cinematic slow dolly over a foggy forest at sunrise",
        generate_audio=False,
        scene_idx=1,
    )
    defaults.update(overrides)
    return SceneMotionRequest(**defaults)


# ---------- payload construction ----------------------------------------


def test_build_payload_text_to_video(fast_provider):
    req = _text_request()
    payload = fast_provider._build_payload(req)
    assert payload["model"] == "bytedance/seedance-2-5"
    inp = payload["input"]
    assert inp["prompt"].startswith("A cinematic")
    assert inp["duration"] == 5
    assert inp["resolution"] == "720p"
    assert inp["aspect_ratio"] == "16:9"
    assert inp["generate_audio"] is False
    assert inp["output_format"] == "mp4"
    # First/last frame fields must NOT be present in text mode.
    assert "first_frame_url" not in inp
    assert "last_frame_url" not in inp
    assert "reference_image_urls" not in inp


def test_build_payload_first_frame_uses_correct_field_name(fast_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_FRAME,
        first_frame_url="https://cdn.example.com/start.png",
        prompt="Slow zoom in on the subject",
    )
    payload = fast_provider._build_payload(req)
    inp = payload["input"]
    assert inp["first_frame_url"] == "https://cdn.example.com/start.png"
    assert "image_url" not in inp  # WRONG name per KIE docs
    assert "image_urls" not in inp
    assert "last_frame_url" not in inp


def test_build_payload_first_and_last_frame(fast_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_AND_LAST_FRAME,
        first_frame_url="https://cdn.example.com/a.png",
        last_frame_url="https://cdn.example.com/b.png",
        prompt="Smooth transformation",
    )
    payload = fast_provider._build_payload(req)
    inp = payload["input"]
    assert inp["first_frame_url"] == "https://cdn.example.com/a.png"
    assert inp["last_frame_url"] == "https://cdn.example.com/b.png"
    assert "end_image_url" not in inp
    assert "reference_image_urls" not in inp


def test_build_payload_multimodal_reference(fast_provider):
    req = _text_request(
        mode=MotionInputMode.MULTIMODAL_REFERENCE,
        prompt="Match the style of the references",
        reference_image_urls=("https://x/1.png", "https://x/2.png"),
    )
    payload = fast_provider._build_payload(req)
    inp = payload["input"]
    assert inp["reference_image_urls"] == ["https://x/1.png", "https://x/2.png"]
    assert "first_frame_url" not in inp
    assert "last_frame_url" not in inp


# ---------- schema validation ---------------------------------------------


def test_rejects_1080p_resolution(fast_provider):
    req = _text_request(resolution="1080p")
    with pytest.raises(ValueError, match="not in Seedance 2.5 API schema"):
        fast_provider._build_payload(req)


def test_rejects_out_of_range_duration(fast_provider):
    req = _text_request(duration_ms=45_000)  # 45 seconds > 30
    with pytest.raises(ValueError, match="outside Seedance 2.5 range"):
        fast_provider._build_payload(req)


def test_rejects_last_frame_alone(fast_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_AND_LAST_FRAME,
        first_frame_url=None,
        last_frame_url="https://x/end.png",
    )
    with pytest.raises(ValueError, match="requires both first_frame_url"):
        fast_provider._build_payload(req)


def test_rejects_first_frame_plus_references(fast_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_FRAME,
        first_frame_url="https://x/a.png",
        reference_image_urls=("https://x/ref1.png",),
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        fast_provider._build_payload(req)


def test_rejects_multimodal_plus_first_frame(fast_provider):
    req = _text_request(
        mode=MotionInputMode.MULTIMODAL_REFERENCE,
        first_frame_url="https://x/a.png",
        reference_image_urls=("https://x/ref1.png",),
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        fast_provider._build_payload(req)


def test_rejects_text_mode_with_images(fast_provider):
    req = _text_request(first_frame_url="https://x/a.png")
    with pytest.raises(ValueError, match="mode=text must not include"):
        fast_provider._build_payload(req)


# ---------- availability + cost estimate ---------------------------------


def test_provider_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    p = KieProvider(api_key="")
    assert p.is_available() is False


def test_estimate_cost_scales_with_duration_and_resolution(fast_provider):
    short = _text_request(duration_ms=5000, resolution="480p")
    long_720 = _text_request(duration_ms=10000, resolution="720p")
    cheap = fast_provider.estimate_cost_cents(short)
    dear = fast_provider.estimate_cost_cents(long_720)
    assert cheap >= 1
    assert dear > cheap


# ---------- full generate() flow — mocked HTTP ---------------------------


@pytest.mark.asyncio
@respx.mock
async def test_generate_success_via_polling(fast_provider):
    task_id = "task_kie_test_1"
    result_video = "https://media.kie.ai/tasks/xyz/final.mp4"

    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "msg": "success", "data": {"taskId": task_id}})
    )
    # First poll: still generating. Second poll: success.
    respx.get(KIE_RECORD_URL).mock(side_effect=[
        httpx.Response(200, json={"code": 200, "data": {"taskId": task_id, "state": "generating"}}),
        httpx.Response(200, json={
            "code": 200,
            "data": {
                "taskId": task_id,
                "state": "success",
                "resultJson": json.dumps({"resultUrls": [result_video]}),
                "creditsConsumed": 45,
                "costTime": 12000,
            },
        }),
    ])

    result = await fast_provider.generate(_text_request())
    assert result.ok is True
    assert result.status == ProviderStatus.SUCCEEDED
    assert result.provider == "kie"
    assert result.model == "bytedance/seedance-2-5"
    assert result.output_url == result_video
    assert result.external_task_id == task_id
    assert result.actual_cost_credits == 45.0
    assert result.estimated_cost_cents >= 1


@pytest.mark.asyncio
@respx.mock
async def test_generate_maps_fail_state(fast_provider):
    task_id = "task_kie_test_fail"
    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"taskId": task_id}})
    )
    respx.get(KIE_RECORD_URL).mock(return_value=httpx.Response(
        200,
        json={
            "code": 200,
            "data": {
                "taskId": task_id,
                "state": "fail",
                "failCode": "501",
                "failMsg": "generation failed upstream",
            },
        },
    ))
    result = await fast_provider.generate(_text_request())
    assert result.ok is False
    assert result.status == ProviderStatus.FAILED
    assert result.error_code == "501"
    assert "generation failed" in (result.error or "")


@pytest.mark.asyncio
@respx.mock
async def test_generate_maps_402_insufficient_credits(fast_provider):
    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(402, json={"code": 402, "msg": "insufficient credits"})
    )
    result = await fast_provider.generate(_text_request())
    assert result.ok is False
    assert result.error_code == "insufficient_credits"


@pytest.mark.asyncio
@respx.mock
async def test_generate_maps_429_rate_limit(fast_provider):
    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(429, json={"code": 429, "msg": "rate limit"})
    )
    result = await fast_provider.generate(_text_request())
    assert result.ok is False
    assert result.error_code == "rate_limited"


@pytest.mark.asyncio
@respx.mock
async def test_generate_empty_result_urls_treated_as_failure(fast_provider):
    task_id = "task_kie_empty"
    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"taskId": task_id}})
    )
    respx.get(KIE_RECORD_URL).mock(return_value=httpx.Response(
        200,
        json={
            "code": 200,
            "data": {
                "taskId": task_id,
                "state": "success",
                "resultJson": json.dumps({"resultUrls": []}),
            },
        },
    ))
    result = await fast_provider.generate(_text_request())
    assert result.ok is False
    assert result.error_code == "empty_result_urls"


@pytest.mark.asyncio
@respx.mock
async def test_generate_never_logs_api_key(fast_provider, caplog):
    """Regression guard: the API key must never appear in log records or errors."""
    caplog.set_level("DEBUG")
    respx.post(KIE_CREATE_URL).mock(return_value=httpx.Response(500, text="oops"))
    result = await fast_provider.generate(_text_request())
    assert result.ok is False
    # The API key must not appear in any log message or error string
    joined = " ".join(r.getMessage() for r in caplog.records) + " " + (result.error or "")
    assert "test-key-do-not-use" not in joined
