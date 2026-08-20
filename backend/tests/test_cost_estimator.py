"""Tests for the cost estimator + hard ceiling enforcement.

Uses the model registry — KIE only "available" when KIE_API_KEY is set
AND at least one KIE model is enabled via KIE_MODELS_ENABLED.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.cost_estimator import (  # noqa: E402
    enforce_render_cost_ceiling,
    estimate_render_cost,
    estimate_scene_cost,
)
from providers.kie_models import reload_specs  # noqa: E402
from providers.registry import reset_registry  # noqa: E402
from providers.types import MotionInputMode, SceneMotionRequest  # noqa: E402


def _req(idx=0, duration_ms=5000, resolution="720p", input_kind="ai_generated"):
    return SceneMotionRequest(
        mode=MotionInputMode.TEXT,
        duration_ms=duration_ms,
        aspect_ratio="16:9",
        resolution=resolution,
        prompt="test scene",
        scene_idx=idx,
        input_kind=input_kind,
    )


@pytest.fixture(autouse=True)
def _seedance_enabled(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    monkeypatch.setenv("KIE_DEFAULT_MODEL", "seedance-2-5")
    reset_registry()
    reload_specs()
    yield
    reset_registry()
    reload_specs()


def test_estimate_local_ken_burns_is_free():
    b = estimate_scene_cost(_req(), provider_hint="local_ken_burns")
    assert b.provider == "local_ken_burns"
    assert b.estimated_cents == 0


def test_estimate_local_video_is_free():
    b = estimate_scene_cost(_req(), provider_hint="local_video")
    assert b.provider == "local_video"
    assert b.estimated_cents == 0


def test_video_input_forces_local_regardless_of_hint():
    """input_kind=video overrides any 'premium' hint the customer may send."""
    req = _req(input_kind="video")
    b = estimate_scene_cost(req, provider_hint="auto")
    assert b.provider == "local_video"
    assert b.estimated_cents == 0


def test_uploaded_image_and_stock_force_local_regardless_of_hint():
    for input_kind in ("image", "stock"):
        b = estimate_scene_cost(_req(input_kind=input_kind), provider_hint="kie")
        assert b.provider == "local_ken_burns"
        assert b.estimated_cents == 0


def test_seedance_720p_no_video_input_matches_rate_card():
    """5s @ 720p no-video-input = ceil(5 × 31.5) = 158¢."""
    b = estimate_scene_cost(_req(duration_ms=5000, resolution="720p"), provider_hint="kie")
    assert b.provider == "kie"
    assert b.estimated_cents == 158


def test_seedance_480p_no_video_input_matches_rate_card():
    """5s @ 480p no-video-input = ceil(5 × 14) = 70¢."""
    b = estimate_scene_cost(_req(duration_ms=5000, resolution="480p"), provider_hint="kie")
    assert b.provider == "kie"
    assert b.estimated_cents == 70


def test_estimate_render_flags_over_ai_limit():
    scenes = [
        (_req(idx=0), "kie"),
        (_req(idx=1), "kie"),
        (_req(idx=2), "kie"),
    ]
    estimate = estimate_render_cost(scenes, max_ai_scenes=2, cap_cents=10_000)
    assert estimate.ai_scene_count == 3
    assert estimate.over_ai_limit is True
    err = enforce_render_cost_ceiling(estimate)
    assert err is not None
    assert "limit is 2" in err


def test_estimate_render_flags_over_cap():
    # 3 × 158¢ = 474¢. Cap 100 → over_cap.
    scenes = [(_req(idx=i), "kie") for i in range(3)]
    estimate = estimate_render_cost(scenes, max_ai_scenes=50, cap_cents=100)
    assert estimate.over_cap is True
    err = enforce_render_cost_ceiling(estimate)
    assert err is not None


def test_estimate_mixed_local_and_ai_only_counts_ai():
    scenes = [
        (_req(idx=0), "local_ken_burns"),
        (_req(idx=1), "kie"),
        (_req(idx=2), "local_video"),
        (_req(idx=3), "kie"),
    ]
    estimate = estimate_render_cost(scenes, max_ai_scenes=2, cap_cents=10_000)
    assert estimate.ai_scene_count == 2
    assert estimate.over_ai_limit is False


def test_estimate_returns_ok_when_within_limits():
    scenes = [(_req(idx=0), "kie")]
    estimate = estimate_render_cost(scenes, max_ai_scenes=2, cap_cents=1000)
    assert enforce_render_cost_ceiling(estimate) is None


def test_three_call_paid_test_math():
    """The user's rate-card check: 480p×5s + 720p×5s (i2v) + 720p×5s (t2v).

    Should be approximately $3.85 total.
    """
    r1 = estimate_scene_cost(_req(duration_ms=5000, resolution="480p"), provider_hint="kie")
    r2 = estimate_scene_cost(_req(duration_ms=5000, resolution="720p"), provider_hint="kie")
    r3 = estimate_scene_cost(_req(duration_ms=5000, resolution="720p"), provider_hint="kie")
    total = r1.estimated_cents + r2.estimated_cents + r3.estimated_cents
    # 70 + 158 + 158 = 386¢ = $3.86 — within a rounding-cent of $3.85.
    assert 384 <= total <= 386
