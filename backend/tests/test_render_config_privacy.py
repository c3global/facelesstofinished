from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from providers.kie_models import reload_specs
from providers.registry import reset_registry
from routes.render_config import build_router


class _User:
    def __init__(self, is_admin: bool) -> None:
        self.is_admin = is_admin


def _client(is_admin: bool) -> TestClient:
    app = FastAPI()

    async def current_user():
        return _User(is_admin)

    app.include_router(build_router(current_user), prefix="/api")
    return TestClient(app)


def _scene(idx=0, **overrides):
    value = {
        "scene_idx": idx,
        "mode": "text",
        "motion_quality": "premium",
        "duration_ms": 5000,
        "prompt": "founder working at desk",
        "source_kind": "ai_generated",
    }
    value.update(overrides)
    return value


def _enable_motion_registry(monkeypatch):
    monkeypatch.setenv("KIE_API_KEY", "test-key")
    monkeypatch.setenv("KIE_MODELS_ENABLED", "seedance-2-5")
    reset_registry()
    reload_specs()


def test_public_capability_never_names_provider(monkeypatch):
    _enable_motion_registry(monkeypatch)
    body = _client(False).get("/api/config/render-providers").json()
    assert body == {"has_premium_motion": True}
    assert "kie" not in str(body).lower()
    assert "fal" not in str(body).lower()


def test_customer_estimate_hides_provider_model_task_and_money(monkeypatch):
    _enable_motion_registry(monkeypatch)
    response = _client(False).post("/api/render/estimate", json={"scenes": [_scene()]})
    assert response.status_code == 200
    body = response.json()
    tokens = set(re.findall(r"[a-z_]+", str(body).lower()))
    for forbidden in ("kie", "fal", "provider", "model", "task", "cents", "dollar"):
        assert forbidden not in tokens
    assert body["scenes"][0]["quality_level"] == "premium"


def test_uploaded_media_estimates_local_and_free_for_admin(monkeypatch):
    _enable_motion_registry(monkeypatch)
    admin = _client(True)
    for source_kind in ("uploaded_image", "uploaded_video", "stock"):
        body = admin.post(
            "/api/admin/render/estimate",
            json={"scenes": [_scene(source_kind=source_kind)]},
        ).json()
        assert body["total_cents"] == 0
        assert body["ai_scene_count"] == 0
        assert body["scenes"][0]["provider"].startswith("local_")


def test_admin_routes_are_gated_and_keep_internal_detail(monkeypatch):
    _enable_motion_registry(monkeypatch)
    assert _client(False).get("/api/admin/render/providers").status_code == 403
    body = _client(True).post(
        "/api/admin/render/estimate", json={"scenes": [_scene()]}
    ).json()
    assert body["scenes"][0]["provider"] == "kie"
    assert body["total_cents"] > 0
