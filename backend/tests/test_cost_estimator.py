"""Tests for the cost estimator + hard ceiling enforcement."""

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
from providers.registry import reset_registry  # noqa: E402
from providers.types import MotionInputMode, SceneMotionRequest  # noqa: E402


def _req(idx=0, duration_ms=5000, resolution="720p"):
    return SceneMotionRequest(
        mode=MotionInputMode.TEXT,
        duration_ms=duration_ms,
        aspect_ratio="16:9",
        resolution=resolution,
        prompt="test scene",
        scene_idx=idx,
    )


def test_estimate_local_ken_burns_is_free(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    reset_registry()
    b = estimate_scene_cost(_req(), provider_hint="local_ken_burns")
    assert b.provider == "local_ken_burns"
    assert b.estimated_cents == 0


def test_estimate_local_video_is_free(monkeypatch):
    reset_registry()
    b = estimate_scene_cost(_req(), provider_hint="local_video")
    assert b.provider == "local_video"
    assert b.estimated_cents == 0


def test_estimate_kie_is_positive(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("KIE_PRICE_CENTS_720P_PER_SEC", "3.0")
    reset_registry()
    b = estimate_scene_cost(_req(duration_ms=5000, resolution="720p"), provider_hint="kie")
    assert b.provider == "kie"
    assert b.estimated_cents >= 1


def test_estimate_render_flags_over_ai_limit(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
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


def test_estimate_render_flags_over_cap(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("KIE_PRICE_CENTS_720P_PER_SEC", "50.0")  # very expensive to blow cap
    reset_registry()
    scenes = [(_req(duration_ms=10_000), "kie") for _ in range(5)]
    estimate = estimate_render_cost(scenes, max_ai_scenes=50, cap_cents=100)
    assert estimate.over_cap is True
    err = enforce_render_cost_ceiling(estimate)
    assert err is not None
    assert "exceeds cap" in err


def test_estimate_mixed_local_and_ai_only_counts_ai(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    scenes = [
        (_req(idx=0), "local_ken_burns"),
        (_req(idx=1), "kie"),
        (_req(idx=2), "local_video"),
        (_req(idx=3), "kie"),
    ]
    estimate = estimate_render_cost(scenes, max_ai_scenes=2, cap_cents=10_000)
    assert estimate.ai_scene_count == 2  # only the two kie scenes count
    assert estimate.over_ai_limit is False


def test_estimate_returns_ok_when_within_limits(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    scenes = [(_req(idx=0), "kie")]
    estimate = estimate_render_cost(scenes, max_ai_scenes=2, cap_cents=10_000)
    assert enforce_render_cost_ceiling(estimate) is None
