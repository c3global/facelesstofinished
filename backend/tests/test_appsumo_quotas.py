"""Pytest suite for AppSumo tier limit enforcement at the Studio render and
Shorts (Sprint Mode) endpoints — approved by Charity 2026-07-02.

Tier limits under test (appsumo_routes.APPSUMO_TIER_LIMITS):
  Tier 1: no Sprint, no Studio renders
  Tier 2: Sprint + 3 Faceless videos/month, no Avatar
  Tier 3: Sprint + 10 Faceless + 3 Avatar videos/month
Non-AppSumo buyers (Pinball/admin-granted) must remain unlimited.

ZERO real API spend: server.db is swapped for mongomock and the render /
script pipelines are stubbed out before any endpoint is called.

Run: `cd /app && pytest backend/tests/test_appsumo_quotas.py -v`
"""
import os
import sys

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, "/app/backend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "f48_appsumo_quota_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import appsumo_routes  # noqa: E402
import server  # noqa: E402


async def _noop_render(job_id):  # replaces server._run_render
    return None


async def _stub_enqueue(**kwargs):  # replaces server._enqueue_script
    return {"id": "stub-script", "status": "queued", "mode": kwargs.get("mode")}


@pytest_asyncio.fixture()
async def env(monkeypatch):
    db = AsyncMongoMockClient()["f48_quota_test"]
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(appsumo_routes, "APPSUMO_TIER_LIMITS",
                        appsumo_routes.DEFAULT_APPSUMO_TIER_LIMITS)
    monkeypatch.setattr(server, "_run_render", _noop_render)
    monkeypatch.setattr(server, "_enqueue_script", _stub_enqueue)
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as c:
        yield c, db


def _auth(email):
    token = server.issue_jwt(email, ["base", "shorts", "studio"])
    return {"Authorization": f"Bearer {token}"}


async def _seed_buyer(db, email, *, source, tier=None):
    doc = {"email": email, "entitlements": ["base", "shorts", "studio"], "source": source}
    if tier is not None:
        doc["appsumo_tier"] = tier
    await db.buyers.insert_one(doc)


RENDER_BODY = {"mode": "faceless", "script": "A short test script.", "scenes": []}


async def test_tier2_faceless_quota_three_per_month(env):
    client, db = env
    await _seed_buyer(db, "t2@x.com", source="appsumo", tier=2)
    for i in range(3):
        r = await client.post("/api/studio/render", json=RENDER_BODY, headers=_auth("t2@x.com"))
        assert r.status_code == 200, f"render {i + 1}: {r.text}"
    r = await client.post("/api/studio/render", json=RENDER_BODY, headers=_auth("t2@x.com"))
    assert r.status_code == 403
    assert "3 of the 3" in r.json()["detail"] or "3" in r.json()["detail"]


async def test_tier2_avatar_not_included(env):
    client, db = env
    await _seed_buyer(db, "t2@x.com", source="appsumo", tier=2)
    r = await client.post("/api/studio/render",
                          json={**RENDER_BODY, "mode": "avatar"}, headers=_auth("t2@x.com"))
    assert r.status_code == 403
    assert "aren't included" in r.json()["detail"]


async def test_tier3_avatar_quota_and_composite_counts_as_avatar(env):
    client, db = env
    await _seed_buyer(db, "t3@x.com", source="appsumo", tier=3)
    for mode in ("avatar", "composite", "avatar"):
        r = await client.post("/api/studio/render",
                              json={**RENDER_BODY, "mode": mode}, headers=_auth("t3@x.com"))
        assert r.status_code == 200, r.text
    r = await client.post("/api/studio/render",
                          json={**RENDER_BODY, "mode": "avatar"}, headers=_auth("t3@x.com"))
    assert r.status_code == 403


async def test_failed_renders_do_not_consume_quota(env):
    client, db = env
    await _seed_buyer(db, "t2@x.com", source="appsumo", tier=2)
    for _ in range(2):
        r = await client.post("/api/studio/render", json=RENDER_BODY, headers=_auth("t2@x.com"))
        assert r.status_code == 200
    await db.renders.update_one({"user_email": "t2@x.com"}, {"$set": {"status": "failed"}})
    # 2 created, 1 flipped to failed → only 1 counts, so a 3rd render fits.
    r = await client.post("/api/studio/render", json=RENDER_BODY, headers=_auth("t2@x.com"))
    assert r.status_code == 200


async def test_non_appsumo_buyer_is_unlimited(env):
    client, db = env
    await _seed_buyer(db, "pinball@x.com", source="webhook")
    for _ in range(5):
        r = await client.post("/api/studio/render", json=RENDER_BODY, headers=_auth("pinball@x.com"))
        assert r.status_code == 200
    r = await client.post("/api/studio/render",
                          json={**RENDER_BODY, "mode": "avatar"}, headers=_auth("pinball@x.com"))
    assert r.status_code == 200


async def test_both_aspects_requires_room_for_two_jobs(env):
    client, db = env
    await _seed_buyer(db, "t2@x.com", source="appsumo", tier=2)
    # 2 of 3 used → both-aspects (2 more) must be rejected.
    for _ in range(2):
        r = await client.post("/api/studio/render", json=RENDER_BODY, headers=_auth("t2@x.com"))
        assert r.status_code == 200
    r = await client.post("/api/studio/render/both-aspects", json=RENDER_BODY,
                          headers=_auth("t2@x.com"))
    assert r.status_code == 403


async def test_sprint_blocked_for_tier1_allowed_for_tier2(env):
    client, db = env
    await _seed_buyer(db, "t1@x.com", source="appsumo", tier=1)
    await _seed_buyer(db, "t2@x.com", source="appsumo", tier=2)
    body = {"topic": "test topic", "platform": "youtube", "sprint": True}
    r = await client.post("/api/scripts/shorts", json=body, headers=_auth("t1@x.com"))
    assert r.status_code == 403
    assert "Sprint Mode" in r.json()["detail"]
    r = await client.post("/api/scripts/shorts", json=body, headers=_auth("t2@x.com"))
    assert r.status_code == 200
    # Plain (non-sprint) shorts stay available to tier 1.
    r = await client.post("/api/scripts/shorts",
                          json={"topic": "t", "platform": "youtube"}, headers=_auth("t1@x.com"))
    assert r.status_code == 200
