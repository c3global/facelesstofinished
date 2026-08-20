"""Regression coverage for the v1.20.15 Studio submission incident."""

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Motor/GridFS binds to the current loop during server import.
asyncio.set_event_loop(asyncio.new_event_loop())

import server  # noqa: E402


def _payload(scene_count: int) -> server.RenderRequest:
    return server.RenderRequest(
        mode="faceless",
        script="Regression test script",
        scenes=[{"source": "ai", "prompt": f"scene {i}"} for i in range(scene_count)],
    )


def test_admin_bypasses_customer_premium_motion_ceiling(monkeypatch):
    monkeypatch.setenv("MAX_AI_SCENES_PER_RENDER", "2")
    user = server.AuthUser(email="owner@example.com", is_admin=True)

    server._enforce_premium_motion_scene_limit(_payload(6), user)


def test_customer_still_receives_premium_motion_ceiling(monkeypatch):
    monkeypatch.setenv("MAX_AI_SCENES_PER_RENDER", "2")
    user = server.AuthUser(email="customer@example.com", is_admin=False)

    with pytest.raises(HTTPException) as exc:
        server._enforce_premium_motion_scene_limit(_payload(3), user)

    assert exc.value.status_code == 400
    assert "2 max" in exc.value.detail


def test_uploaded_media_remains_outside_ai_limit(monkeypatch):
    monkeypatch.setenv("MAX_AI_SCENES_PER_RENDER", "1")
    payload = server.RenderRequest(
        mode="faceless",
        script="Uploaded B-roll test",
        scenes=[
            {"source": "uploaded", "kind": "video"},
            {"source": "uploaded", "kind": "image", "motion_quality": "standard"},
        ],
    )
    user = server.AuthUser(email="customer@example.com", is_admin=False)

    server._enforce_premium_motion_scene_limit(payload, user)


def test_single_render_submission_is_inserted_into_history_source():
    source = (BACKEND.parent / "frontend" / "src" / "pages" / "Studio.jsx").read_text()
    expected = "setHistory((h) => [r.data, ...h.filter((row) => row.id !== r.data.id)])"

    # Normal submission and regeneration must both preserve the new row.
    assert source.count(expected) >= 2


def test_kie_label_is_admin_only_in_storyboard_source():
    source = (BACKEND.parent / "frontend" / "src" / "pages" / "Studio.jsx").read_text()

    assert 'isAdmin ? "KIE AI still" : "AI still"' in source
    assert 'isAdmin ? "KIE AI still + motion" : "AI still + motion"' in source
