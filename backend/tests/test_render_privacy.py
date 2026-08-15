"""Customer-vs-admin privacy tests for render endpoints.

Locks the customer-facing privacy rule from 2026-08-15:
  * Customer responses NEVER contain: cost cents/dollars, provider name,
    model id, cap value, KIE/fal task ids.
  * Admin responses MAY contain all of the above.
Applies to:
  * GET /api/config/render-providers (public — no cost/provider names)
  * POST /api/render/estimate (customer view)
  * POST /api/admin/render/estimate (admin view)
  * GET  /api/admin/render/providers (admin view)
  * _scrub_render_for_response helper on studio history + render status
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.registry import reset_registry  # noqa: E402
from routes.render_config import build_router  # noqa: E402


# ---- Test scaffolding ----------------------------------------------------


class _StubUser:
    def __init__(self, is_admin: bool, email: str = "u@example.com") -> None:
        self.is_admin = is_admin
        self.email = email
        self.entitlements = ["base", "studio"]


def _make_app(*, is_admin: bool) -> TestClient:
    app = FastAPI()

    async def _current_user() -> _StubUser:
        return _StubUser(is_admin=is_admin)

    app.include_router(build_router(current_user_dep=_current_user), prefix="/api")
    return TestClient(app)


def _sample_scene(idx: int = 0, motion_quality: str = "premium") -> dict[str, Any]:
    return {
        "scene_idx": idx,
        "mode": "text",
        "motion_quality": motion_quality,
        "duration_ms": 5000,
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "prompt": "test scene",
    }


# ---- Public /config/render-providers ------------------------------------


def test_public_providers_never_reveals_names(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    monkeypatch.setenv("FAL_API_KEY", "fal-fake")
    reset_registry()
    c = _make_app(is_admin=False)
    r = c.get("/api/config/render-providers")
    assert r.status_code == 200
    body = r.json()
    # Only the opaque capability flag is exposed.
    assert set(body.keys()) == {"has_premium_motion"}
    assert body["has_premium_motion"] is True
    # Explicitly assert no provider name leaks (any casing).
    for token in ("kie", "fal", "seedance", "kling", "bytedance", "flux"):
        assert token not in str(body).lower()


def test_public_providers_reports_no_premium_when_none_available(monkeypatch):
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    monkeypatch.delenv("FAL_API_KEY", raising=False)
    reset_registry()
    c = _make_app(is_admin=False)
    body = c.get("/api/config/render-providers").json()
    assert body == {"has_premium_motion": False}


# ---- Admin /admin/render/providers --------------------------------------


def test_admin_providers_gated(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    non_admin = _make_app(is_admin=False)
    admin = _make_app(is_admin=True)
    assert non_admin.get("/api/admin/render/providers").status_code == 403
    admin_body = admin.get("/api/admin/render/providers").json()
    assert "available" in admin_body
    assert "default" in admin_body
    assert "kie" in admin_body["available"]


# ---- Customer /render/estimate ------------------------------------------


def test_customer_estimate_hides_all_cost_and_provider_fields(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    c = _make_app(is_admin=False)
    r = c.post("/api/render/estimate", json={"scenes": [_sample_scene(0), _sample_scene(1, "standard")]})
    assert r.status_code == 200, r.text
    body = r.json()
    # Positive assertions on customer-safe fields
    assert body["ai_scene_count"] == 1
    assert body["total_scene_count"] == 2
    assert isinstance(body["estimated_completion_seconds"], int)
    assert body["over_capacity"] is False
    # Each scene has quality_level + is_ai_motion — no cost, no provider name
    for s in body["scenes"]:
        assert s["quality_level"] in ("standard", "premium")
        assert isinstance(s["is_ai_motion"], bool)
        # NEGATIVE assertions — these keys must not be in the response
        for forbidden in ("estimated_cents", "cost_cents", "provider", "model"):
            assert forbidden not in s
    # Top-level forbidden keys
    for forbidden in (
        "total_cents",
        "cap_cents",
        "max_ai_scenes",
        "provider_selected",
    ):
        assert forbidden not in body
    # And no leakage anywhere in the body — check on tokenized boundaries so
    # words like "false" don't accidentally match "fal".
    import re

    body_tokens = set(re.findall(r"[a-z_]+", str(body).lower()))
    for token in ("kie", "fal", "seedance", "kling", "bytedance", "flux", "cents", "dollar", "dollars"):
        assert token not in body_tokens


def test_customer_over_capacity_reason_is_generic(monkeypatch):
    """Over-capacity messages must not reveal specific cost caps."""
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    c = _make_app(is_admin=False)
    # 5 AI scenes to force over_ai_limit (default max is 2).
    scenes = [_sample_scene(i, "premium") for i in range(5)]
    body = c.post("/api/render/estimate", json={"scenes": scenes}).json()
    assert body["over_capacity"] is True
    reason = (body.get("over_capacity_reason") or "").lower()
    # Reason must reference plan capacity, not a dollar amount or cap.
    for token in ("¢", "$", "cent", "dollar"):
        assert token not in reason


def test_customer_cannot_override_admin_caps(monkeypatch):
    """Non-admin sending cap_cents / max_ai_scenes must not affect the estimate."""
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    c = _make_app(is_admin=False)
    # Try to raise max_ai_scenes so 3 premium scenes wouldn't trip the limit.
    body = c.post(
        "/api/render/estimate",
        json={"scenes": [_sample_scene(i, "premium") for i in range(3)], "max_ai_scenes": 999},
    ).json()
    # Server ignores the override — 3 > default max of 2 → over_capacity.
    assert body["over_capacity"] is True


# ---- Admin /admin/render/estimate ---------------------------------------


def test_admin_estimate_returns_cents_and_provider(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    admin = _make_app(is_admin=True)
    body = admin.post(
        "/api/admin/render/estimate",
        json={"scenes": [_sample_scene(0, "premium")]},
    ).json()
    # Admin-only fields must be present
    assert "total_cents" in body
    assert "cap_cents" in body
    assert "max_ai_scenes" in body
    assert body["scenes"][0]["provider"] in ("kie", "fal", "auto")
    assert body["scenes"][0]["estimated_cents"] >= 0


def test_admin_estimate_forbidden_for_non_admin(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "kie-fake")
    reset_registry()
    c = _make_app(is_admin=False)
    r = c.post("/api/admin/render/estimate", json={"scenes": [_sample_scene(0)]})
    assert r.status_code == 403


# ---- _scrub_render_for_response helper (server.py) ----------------------


def test_scrub_render_removes_cost_and_provider_for_customer():
    from server import _scrub_render_for_response  # noqa: WPS433

    raw = {
        "id": "job_1",
        "status": "complete",
        "progress": 100,
        "estimated_cost_cents": 42,
        "actual_cost_cents": 45,
        "ai_engine": "kling",
        "provider": "kie",
        "kie_task_id": "task_kie_xyz",
        "final_url": "https://r2/final.mp4",
        "scenes": [
            {"idx": 0, "provider": "kie", "model": "bytedance/seedance-2-5", "external_task_id": "task_1", "duration_ms": 5000},
            {"idx": 1, "provider": "local", "duration_ms": 4000},
        ],
        "scene_overrides": [{"idx": 0, "provider": "kie", "freeze_end": True}],
    }
    clean = _scrub_render_for_response(raw, is_admin=False)
    # Public fields survive
    assert clean["id"] == "job_1"
    assert clean["status"] == "complete"
    assert clean["progress"] == 100
    assert clean["final_url"] == "https://r2/final.mp4"
    # Forbidden fields are gone
    for k in ("estimated_cost_cents", "actual_cost_cents", "ai_engine", "provider", "kie_task_id"):
        assert k not in clean
    # Nested scene sanitization
    for scene in clean["scenes"]:
        for k in ("provider", "model", "external_task_id"):
            assert k not in scene
    for override in clean["scene_overrides"]:
        assert "provider" not in override
        # Non-forbidden fields preserved
        assert "freeze_end" in override


def test_scrub_render_leaves_admin_untouched():
    from server import _scrub_render_for_response  # noqa: WPS433

    raw = {
        "id": "job_1",
        "actual_cost_cents": 45,
        "provider": "kie",
        "scenes": [{"idx": 0, "model": "bytedance/seedance-2-5"}],
    }
    clean = _scrub_render_for_response(raw, is_admin=True)
    # Admins see everything (same object reference is acceptable here)
    assert clean.get("actual_cost_cents") == 45
    assert clean["scenes"][0]["model"] == "bytedance/seedance-2-5"
