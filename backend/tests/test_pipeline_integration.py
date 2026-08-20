"""Mocked integration tests for the provider-registry ↔ render pipeline bridge.

These tests exercise the actual functions server.py calls (via
``providers.pipeline``) — not the isolated adapter. They demonstrate:

  1. AI-motion scenes route through mocked KIE when the feature flag
     is on AND the model is enabled.
  2. Stock scenes never touch the provider registry.
  3. Uploaded videos short-circuit to local_video (free) regardless of
     the customer's motion quality choice.
  4. Uploaded images always stay local and never trigger a paid provider.
  5. Fal-fallback path fires when the registry declines (flag off /
     no enabled models / provider returns None).
  6. Customer-visible response never carries provider, model, task_id,
     or cost fields (locked via _scrub_render_for_response).
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

from providers.kie_models import reload_specs  # noqa: E402
from providers.kie_provider import KIE_CREATE_URL, KIE_RECORD_URL  # noqa: E402
from providers.pipeline import (  # noqa: E402
    ProviderPipelineRejected,
    enforce_pipeline_ceiling,
    resolve_scene_input_kind,
    result_to_scene_telemetry,
    run_provider_motion,
    use_registry_enabled,
)
from providers.registry import reset_registry  # noqa: E402
from providers.types import (  # noqa: E402
    MotionInputMode,
    ProviderStatus,
    SceneMotionRequest,
)


# ---------- fixtures ------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Reset env + registry cache between tests."""
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    monkeypatch.setenv("KIE_DEFAULT_MODEL", "seedance-2-5")
    monkeypatch.setenv("KIE_POLL_INTERVAL_S", "0.01")
    monkeypatch.setenv("KIE_MAX_WAIT_S", "5.0")
    reset_registry()
    reload_specs()
    yield
    reset_registry()
    reload_specs()


def _ai_scene(idx=0, resolution="720p", input_kind="ai_generated") -> SceneMotionRequest:
    return SceneMotionRequest(
        mode=MotionInputMode.TEXT,
        duration_ms=5000,
        aspect_ratio="16:9",
        resolution=resolution,
        prompt=f"cinematic scene {idx}",
        scene_idx=idx,
        input_kind=input_kind,
    )


def _first_frame_scene(idx=0) -> SceneMotionRequest:
    return SceneMotionRequest(
        mode=MotionInputMode.FIRST_FRAME,
        duration_ms=5000,
        aspect_ratio="9:16",
        resolution="720p",
        prompt="slow zoom",
        first_frame_url="https://cdn.example.com/still.png",
        scene_idx=idx,
        input_kind="image",
    )


# ---------- resolve_scene_input_kind (media type preservation) -----------


def test_input_kind_prefers_explicit_kind_field():
    """MediaLibrary.jsx writes ``kind: 'video'`` — pipeline must honour it."""
    assert resolve_scene_input_kind({"source": "uploaded", "kind": "video"}) == "video"
    assert resolve_scene_input_kind({"source": "uploaded", "kind": "image"}) == "image"


def test_input_kind_sniffs_url_extension_for_legacy_payloads():
    """Legacy uploaded scenes without kind sniff the URL extension."""
    assert resolve_scene_input_kind({"source": "uploaded", "video_url": "https://x/y.mp4"}) == "video"
    assert resolve_scene_input_kind({"source": "uploaded", "video_url": "https://x/y.PNG"}) == "image"


def test_input_kind_maps_source_ai_and_stock():
    assert resolve_scene_input_kind({"source": "ai"}) == "ai_generated"
    assert resolve_scene_input_kind({"source": "pexels"}) == "stock"


def test_input_kind_uploaded_default_is_image():
    """Uploaded without extension or kind → image (safe local Ken Burns path)."""
    assert resolve_scene_input_kind({"source": "uploaded"}) == "image"


# ---------- Feature flag gates the whole thing ---------------------------


@pytest.mark.asyncio
async def test_registry_disabled_by_default(monkeypatch):
    monkeypatch.delenv("USE_PROVIDER_REGISTRY", raising=False)
    monkeypatch.setenv("KIE_API_KEY", "k")
    assert use_registry_enabled() is False
    result = await run_provider_motion(_ai_scene())
    assert result is None  # None means "fall back to legacy fal path"


@pytest.mark.asyncio
async def test_registry_falls_back_when_no_kie_key(monkeypatch):
    monkeypatch.setenv("USE_PROVIDER_REGISTRY", "1")
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)  # ensure BOTH providers hidden
    reset_registry()
    reload_specs()
    result = await run_provider_motion(_ai_scene())
    assert result is None  # No provider available → fall back


@pytest.mark.asyncio
async def test_registry_falls_back_when_model_not_enabled(monkeypatch):
    monkeypatch.setenv("USE_PROVIDER_REGISTRY", "1")
    monkeypatch.setenv("KIE_API_KEY", "k")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "")
    monkeypatch.delenv("FAL_API_KEY", raising=False)  # no legacy fallback either
    reset_registry()
    reload_specs()
    result = await run_provider_motion(_ai_scene())
    assert result is None


# ---------- Actual routing through mocked KIE ----------------------------


@pytest.mark.asyncio
@respx.mock
async def test_ai_text_scene_routes_through_kie(monkeypatch):
    monkeypatch.setenv("USE_PROVIDER_REGISTRY", "1")
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()

    respx.post(KIE_CREATE_URL).mock(
        return_value=httpx.Response(200, json={"code": 200, "data": {"taskId": "task_ai_text"}})
    )
    respx.get(KIE_RECORD_URL).mock(
        return_value=httpx.Response(200, json={
            "code": 200,
            "data": {
                "taskId": "task_ai_text",
                "state": "success",
                "resultJson": json.dumps({"resultUrls": ["https://media.kie/ai_text.mp4"]}),
                "creditsConsumed": 12,
            },
        })
    )
    result = await run_provider_motion(_ai_scene(idx=3))
    assert result is not None
    assert result.ok is True
    assert result.provider == "kie"
    assert result.output_url == "https://media.kie/ai_text.mp4"
    assert result.external_task_id == "task_ai_text"


@pytest.mark.asyncio
@respx.mock
async def test_uploaded_image_always_bypasses_kie(monkeypatch):
    """Uploaded B-roll is customer media, so even a premium choice stays local."""
    monkeypatch.setenv("USE_PROVIDER_REGISTRY", "1")
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()

    result = await run_provider_motion(_first_frame_scene(idx=1))
    assert result is None
    assert len(respx.calls) == 0


@pytest.mark.asyncio
@respx.mock
async def test_uploaded_video_and_stock_always_bypass_registry(monkeypatch):
    monkeypatch.setenv("USE_PROVIDER_REGISTRY", "1")
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()
    for input_kind in ("video", "stock"):
        assert await run_provider_motion(_ai_scene(input_kind=input_kind)) is None
    assert len(respx.calls) == 0


# ---------- Ceiling enforcement in the pipeline --------------------------


def test_pipeline_ceiling_rejects_too_many_ai_scenes(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()
    scenes = [(_ai_scene(idx=i), "kie") for i in range(3)]
    with pytest.raises(ProviderPipelineRejected, match="limit is 2"):
        enforce_pipeline_ceiling(scenes, max_ai_scenes=2, cap_cents=10_000)


def test_pipeline_ceiling_rejects_over_cost_cap(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()
    # 3 × 158¢ = 474¢ > cap 100¢
    scenes = [(_ai_scene(idx=i), "kie") for i in range(3)]
    with pytest.raises(ProviderPipelineRejected, match="exceeds cap"):
        enforce_pipeline_ceiling(scenes, max_ai_scenes=50, cap_cents=100)


def test_pipeline_ceiling_passes_within_limits(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()
    scenes = [(_ai_scene(idx=0), "kie")]
    enforce_pipeline_ceiling(scenes, max_ai_scenes=5, cap_cents=1000)  # no raise


def test_pipeline_ceiling_video_input_is_free(monkeypatch):
    """Uploaded videos never consume cost budget."""
    monkeypatch.setenv("KIE_API_KEY", "k")
    reset_registry()
    reload_specs()
    scenes = [(_ai_scene(idx=i, input_kind="video"), "auto") for i in range(10)]
    # 10 uploaded videos, cap 1¢ — still fine because all downgrade to local.
    enforce_pipeline_ceiling(scenes, max_ai_scenes=1, cap_cents=1)  # no raise


# ---------- Scene telemetry never leaks customer-forbidden fields --------


def test_scene_telemetry_stays_in_customer_forbidden_set():
    """Provider, model, upstream task ID, and cost never reach customers."""
    from render_privacy import scrub_render_for_customer  # noqa: WPS433

    fake_result = type("R", (), {
        "provider": "kie",
        "model": "bytedance/seedance-2-5",
        "external_task_id": "task_1",
        "status": ProviderStatus.SUCCEEDED,
        "error": None,
        "estimated_cost_cents": 158,
        "actual_cost_credits": 20.0,
        "output_url": "https://x/final.mp4",
        "duration_ms": 5000,
        "resolution": "720p",
    })
    telemetry = result_to_scene_telemetry(fake_result)  # type: ignore[arg-type]
    scrubbed = scrub_render_for_customer({"_provider_telemetry": telemetry, "scenes": [telemetry]})
    assert "_provider_telemetry" not in scrubbed
    customer_scene = scrubbed["scenes"][0]
    for k in ("provider", "model", "external_task_id", "estimated_cost_cents", "actual_cost_credits"):
        assert k in telemetry
        assert k not in customer_scene
