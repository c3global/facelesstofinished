"""Tests for provider registry — selection + auto-fallback semantics.

Uses the model registry: KIE is only "available" when KIE_API_KEY is
set AND KIE_MODELS_ENABLED includes at least one enabled slug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.kie_models import reload_specs  # noqa: E402
from providers.registry import (  # noqa: E402
    available_providers,
    default_provider_name,
    get_provider,
    reset_registry,
)
from providers.types import MotionInputMode, SceneMotionRequest  # noqa: E402


def _req(mode=MotionInputMode.TEXT):
    return SceneMotionRequest(
        mode=mode,
        duration_ms=5000,
        aspect_ratio="16:9",
        resolution="720p",
        prompt="test",
    )


@pytest.fixture(autouse=True)
def _refresh(monkeypatch):
    reset_registry()
    reload_specs()
    yield
    reset_registry()
    reload_specs()


def test_available_providers_hides_kie_when_no_key(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake-for-test")
    reset_registry()
    reload_specs()
    names = available_providers()
    assert "kie" not in names
    assert "fal" in names


def test_available_providers_hides_kie_when_no_models_enabled(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    reload_specs()
    names = available_providers()
    assert "kie" not in names  # No models enabled → provider hidden
    assert "fal" in names


def test_available_providers_includes_kie_when_configured(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    reload_specs()
    names = available_providers()
    assert "kie" in names
    assert "fal" in names


def test_get_provider_kie_returns_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    reset_registry()
    reload_specs()
    assert get_provider("kie") is None


def test_auto_prefers_kie_when_available(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    reload_specs()
    provider = get_provider("auto", request=_req(MotionInputMode.TEXT))
    assert provider is not None
    assert provider.name == "kie"


def test_auto_returns_none_for_unsupported_mode_when_kie_disabled(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    reload_specs()
    provider = get_provider("auto", request=_req(MotionInputMode.MULTIMODAL_REFERENCE))
    assert provider is None


def test_default_provider_name_from_env(monkeypatch):
    monkeypatch.setenv("RENDER_PROVIDER", "kie")
    assert default_provider_name() == "kie"
    monkeypatch.setenv("RENDER_PROVIDER", "AUTO")
    assert default_provider_name() == "auto"
    monkeypatch.delenv("RENDER_PROVIDER", raising=False)
    assert default_provider_name() == "auto"
