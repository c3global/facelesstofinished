"""Mocked tests for the model-agnostic KieProvider.

Every test uses respx to intercept KIE HTTP traffic. If a test somehow
tries to reach api.kie.ai for real, respx raises so the test fails
loudly instead of billing the account.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.kie_models import get_spec, reload_specs  # noqa: E402
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


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Every test starts with a clean env + reloaded specs."""
    for k in list(monkeypatch._setitem):  # pragma: no cover
        pass  # just to silence lint
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    monkeypatch.setenv("KIE_POLL_INTERVAL_S", "0.01")
    monkeypatch.setenv("KIE_MAX_WAIT_S", "5.0")
    reload_specs()
    yield


@pytest.fixture
def seedance_provider(monkeypatch):
    """Provider bound to seedance-2-5 for these tests."""
    monkeypatch.setenv("KIE_API_KEY", "test-key-do-not-use")
    reload_specs()
    provider = KieProvider.for_slug("seedance-2-5", api_key="test-key-do-not-use")
    assert provider is not None
    return provider


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


def test_build_payload_text_to_video(seedance_provider):
    req = _text_request()
    payload = seedance_provider._build_payload(req)
    assert payload["model"] == "bytedance/seedance-2-5"
    inp = payload["input"]
    assert inp["prompt"].startswith("A cinematic")
    assert inp["duration"] == 5
    assert inp["resolution"] == "720p"
    assert inp["aspect_ratio"] == "16:9"
    assert inp["generate_audio"] is False
    assert inp["output_format"] == "mp4"
    assert "first_frame_url" not in inp
    assert "last_frame_url" not in inp
    assert "reference_image_urls" not in inp


def test_build_payload_first_frame_uses_correct_field_name(seedance_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_FRAME,
        first_frame_url="https://cdn.example.com/start.png",
        prompt="Slow zoom in on the subject",
    )
    payload = seedance_provider._build_payload(req)
    inp = payload["input"]
    assert inp["first_frame_url"] == "https://cdn.example.com/start.png"
    assert "image_url" not in inp
    assert "image_urls" not in inp


def test_build_payload_first_and_last_frame(seedance_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_AND_LAST_FRAME,
        first_frame_url="https://cdn.example.com/a.png",
        last_frame_url="https://cdn.example.com/b.png",
        prompt="Smooth transformation",
    )
    payload = seedance_provider._build_payload(req)
    inp = payload["input"]
    assert inp["first_frame_url"] == "https://cdn.example.com/a.png"
    assert inp["last_frame_url"] == "https://cdn.example.com/b.png"
    assert "end_image_url" not in inp


def test_build_payload_multimodal_reference(seedance_provider):
    req = _text_request(
        mode=MotionInputMode.MULTIMODAL_REFERENCE,
        prompt="Match the style of the references",
        reference_image_urls=("https://x/1.png", "https://x/2.png"),
    )
    payload = seedance_provider._build_payload(req)
    inp = payload["input"]
    assert inp["reference_image_urls"] == ["https://x/1.png", "https://x/2.png"]


# ---------- schema validation ---------------------------------------------


def test_rejects_1080p_resolution(seedance_provider):
    req = _text_request(resolution="1080p")
    with pytest.raises(ValueError, match="not in seedance-2-5 schema"):
        seedance_provider._build_payload(req)


def test_rejects_out_of_range_duration(seedance_provider):
    req = _text_request(duration_ms=45_000)
    with pytest.raises(ValueError, match="outside seedance-2-5 range"):
        seedance_provider._build_payload(req)


def test_rejects_last_frame_alone(seedance_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_AND_LAST_FRAME,
        first_frame_url=None,
        last_frame_url="https://x/end.png",
    )
    with pytest.raises(ValueError, match="requires both first_frame_url"):
        seedance_provider._build_payload(req)


def test_rejects_first_frame_plus_references(seedance_provider):
    req = _text_request(
        mode=MotionInputMode.FIRST_FRAME,
        first_frame_url="https://x/a.png",
        reference_image_urls=("https://x/ref1.png",),
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        seedance_provider._build_payload(req)


# ---------- pricing (KIE 2026-08-15 rate card) ----------------------------


def test_seedance_pricing_720p_no_video_input(seedance_provider):
    """720p, no video input: 31.5¢/output-second. 5-second clip → 158¢."""
    req = _text_request(duration_ms=5000, resolution="720p")
    cents = seedance_provider.estimate_cost_cents(req)
    # 5 × 31.5 = 157.5 → rounded up to 158
    assert cents == 158


def test_seedance_pricing_480p_no_video_input(seedance_provider):
    """480p, no video input: 14¢/output-second. 5-second clip → 70¢."""
    req = _text_request(duration_ms=5000, resolution="480p")
    cents = seedance_provider.estimate_cost_cents(req)
    # 5 × 14 = 70
    assert cents == 70


def test_seedance_three_call_test_total_matches_customer_math(seedance_provider):
    """The three-call test the user computed: 480p×5s + 720p×5s×2 = 386¢ ≈ $3.85.

    (Customer computed $3.85 total, my raw math is 70 + 158 + 158 = 386 — the
    rounding-up ceiling makes it 1¢ higher than 70+157.5+157.5=385. Well
    within the "approximately $3.85" the customer stated.)
    """
    r1 = seedance_provider.estimate_cost_cents(_text_request(duration_ms=5000, resolution="480p"))
    r2 = seedance_provider.estimate_cost_cents(
        _text_request(
            duration_ms=5000, resolution="720p",
            mode=MotionInputMode.FIRST_FRAME, first_frame_url="https://x/a.png",
        )
    )
    r3 = seedance_provider.estimate_cost_cents(_text_request(duration_ms=5000, resolution="720p"))
    total = r1 + r2 + r3
    # Must be within 1¢ of $3.85.
    assert 384 <= total <= 386


def test_pricing_env_override_wins(monkeypatch, seedance_provider):
    """A deployment override on 720p should be respected on next reload."""
    monkeypatch.setenv("KIE_SEEDANCE_2_5_PRICE_CENTS_720P_NO_VIDEO_PER_SEC", "10.0")
    reload_specs()
    fresh = KieProvider.for_slug("seedance-2-5", api_key="test-key-do-not-use")
    cents = fresh.estimate_cost_cents(_text_request(duration_ms=5000, resolution="720p"))
    assert cents == 50  # 5 × 10


# ---------- availability + model registry gating -------------------------


def test_provider_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    p = KieProvider.for_slug("seedance-2-5", api_key="")
    assert p is not None
    assert p.is_available() is False


def test_provider_unavailable_when_model_not_enabled(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "k")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "")  # no models enabled
    reload_specs()
    assert KieProvider.for_slug("seedance-2-5", api_key="k") is None


def test_unknown_model_slug_returns_none(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "k")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    reload_specs()
    assert KieProvider.for_slug("nonexistent-model", api_key="k") is None


# ---------- full generate() flow — mocked HTTP ---------------------------


@pytest.mark.asyncio
@respx.mock
async def test_generate_success_via_polling(seedance_provider):
    task_id = "task_kie_test_1"
    result_video = "https://media.kie.ai/tasks/xyz/final.mp4"

    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "msg": "success", "data": {"taskId": task_id}})
    )
    respx.get(KIE_RECORD_URL).mock(side_effect=[
        httpx.Response(200, json={"code": 200, "data": {"taskId": task_id, "state": "generating"}}),
        httpx.Response(200, json={
            "code": 200,
            "data": {
                "taskId": task_id,
                "state": "success",
                "resultJson": json.dumps({"resultUrls": [result_video]}),
                "creditsConsumed": 45,
            },
        }),
    ])

    result = await seedance_provider.generate(_text_request())
    assert result.ok is True
    assert result.status == ProviderStatus.SUCCEEDED
    assert result.provider == "kie"
    assert result.model == "bytedance/seedance-2-5"
    assert result.output_url == result_video
    assert result.external_task_id == task_id
    assert result.actual_cost_credits == 45.0


@pytest.mark.asyncio
@respx.mock
async def test_generate_maps_fail_state(seedance_provider):
    task_id = "task_kie_test_fail"
    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"taskId": task_id}})
    )
    respx.get(KIE_RECORD_URL).mock(return_value=httpx.Response(200, json={
        "code": 200, "data": {"taskId": task_id, "state": "fail", "failCode": "501", "failMsg": "gen failed"}
    }))
    result = await seedance_provider.generate(_text_request())
    assert result.ok is False


@pytest.mark.asyncio
@respx.mock
async def test_generate_maps_402_insufficient_credits(seedance_provider):
    respx.post(KIE_CREATE_URL).mock(return_value=httpx.Response(402))
    result = await seedance_provider.generate(_text_request())
    assert result.ok is False
    assert result.error_code == "insufficient_credits"


@pytest.mark.asyncio
@respx.mock
async def test_generate_maps_429_rate_limit(seedance_provider):
    respx.post(KIE_CREATE_URL).mock(return_value=httpx.Response(429))
    result = await seedance_provider.generate(_text_request())
    assert result.error_code == "rate_limited"


@pytest.mark.asyncio
@respx.mock
async def test_generate_never_logs_api_key(seedance_provider, caplog):
    caplog.set_level("DEBUG")
    respx.post(KIE_CREATE_URL).mock(return_value=httpx.Response(500, text="oops"))
    result = await seedance_provider.generate(_text_request())
    assert result.ok is False
    joined = " ".join(r.getMessage() for r in caplog.records) + " " + (result.error or "")
    assert "test-key-do-not-use" not in joined
