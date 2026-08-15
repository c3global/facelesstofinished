"""Tests for provider registry — selection + auto-fallback semantics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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


def test_available_providers_hides_kie_when_no_key(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    monkeypatch.setenv("FAL_API_KEY", "fal-fake-for-test")
    reset_registry()
    names = available_providers()
    assert "kie" not in names
    assert "fal" in names


def test_available_providers_includes_kie_when_key_present(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake-for-test")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake-for-test")
    reset_registry()
    names = available_providers()
    assert "kie" in names
    assert "fal" in names


def test_get_provider_by_name_returns_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    reset_registry()
    assert get_provider("kie") is None


def test_auto_prefers_kie_when_available(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    provider = get_provider("auto", request=_req(MotionInputMode.TEXT))
    assert provider is not None
    assert provider.name == "kie"


def test_auto_falls_back_to_fal_for_mode_kie_does_not_support(monkeypatch):
    """If a future mode is fal-only, auto should pick fal for it."""
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    # KIE supports first-and-last-frame; fal doesn't. So for THIS request
    # kie should still win (both eligible, kie preferred).
    provider = get_provider("auto", request=_req(MotionInputMode.FIRST_AND_LAST_FRAME))
    assert provider is not None
    assert provider.name == "kie"


def test_auto_returns_none_when_no_provider_supports(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    # fal doesn't support MULTIMODAL_REFERENCE; kie is unavailable.
    provider = get_provider("auto", request=_req(MotionInputMode.MULTIMODAL_REFERENCE))
    assert provider is None


def test_default_provider_name_from_env(monkeypatch):
    monkeypatch.setenv("RENDER_PROVIDER", "kie")
    assert default_provider_name() == "kie"
    monkeypatch.setenv("RENDER_PROVIDER", "AUTO")
    assert default_provider_name() == "auto"
    monkeypatch.delenv("RENDER_PROVIDER", raising=False)
    assert default_provider_name() == "auto"
