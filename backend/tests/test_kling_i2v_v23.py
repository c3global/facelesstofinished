"""Iter-23 tests — Flux + Kling i2v engine path + flux_static + estimator.

Verifies:
  1. Estimator cost for ai_engine='flux' (Flux + Kling i2v) ~ 60c for 2 AI scenes
  2. Estimator cost for ai_engine='flux_static' ~ 10c (no Kling cost)
  3. Estimator for ai_engine='kling' (T2V) ~ $1.00 (50c x 2)
  4. KLING_I2V_COST_CENTS_5S constant = 25, model id correct
  5. Render queue submission for flux + flux_static does NOT crash
  6. db.kling_i2v_cache write happens when _fal_kling_i2v_generate stubbed

Run:
    python -m pytest /app/backend/tests/test_kling_i2v_v23.py -v \
        --junitxml=/app/test_reports/pytest/iteration_23_kling_i2v.xml
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import time
from unittest.mock import patch, AsyncMock

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://f2f48-video-engine.preview.emergentagent.com",
).rstrip("/")
DEV_EMAIL = "drcharitycampbell@gmail.com"

# Ensure /app/backend importable for direct module checks
sys.path.insert(0, "/app/backend")


def _login_token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": DEV_EMAIL}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, "no token returned"
    return tok


@pytest.fixture(scope="module")
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {_login_token()}"}


def _render_payload(ai_engine: str, n_scenes: int = 2, broll_source="ai", script="hi") -> dict:
    return {
        "mode": "faceless",
        "ai_engine": ai_engine,
        "broll_source": broll_source,
        "aspect": "9_16",
        "script": script,
        "scenes": [
            {"prompt": f"scene {i} prompt about cats", "source": "ai", "weight": 5}
            for i in range(n_scenes)
        ],
        "voice_id": "af_bella",
    }


# ----------------------------------------------------------------------------
# 1) Estimator tests (POST /api/studio/render/estimate)
# ----------------------------------------------------------------------------
class TestEstimator:
    def test_estimate_flux_default_includes_kling_i2v(self, auth_headers):
        """flux: 2 AI scenes => 2*4 (Flux) + 2*25 (Kling i2v) + 2 (compose) + ~0 TTS = ~60c."""
        r = requests.post(
            f"{BASE_URL}/api/studio/render/estimate",
            json=_render_payload("flux", n_scenes=2),
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert "estimated_cost_cents" in body
        cost = body["estimated_cost_cents"]
        # Expected = 8 + 50 + 2 = 60 cents (script len 'hi' so TTS ~0)
        assert 55 <= cost <= 70, f"flux estimate {cost}c not near 60c"
        print(f"[OK] flux estimate = {cost}c (target ~60c)")

    def test_estimate_flux_static_no_kling_cost(self, auth_headers):
        """flux_static: 2 AI scenes => 2*4 (Flux) + 2 (compose) = 10c (NO Kling)."""
        r = requests.post(
            f"{BASE_URL}/api/studio/render/estimate",
            json=_render_payload("flux_static", n_scenes=2),
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        cost = r.json()["estimated_cost_cents"]
        # 8 + 2 = 10. Allow 8..14
        assert 8 <= cost <= 14, f"flux_static estimate {cost}c not near 10c"
        print(f"[OK] flux_static estimate = {cost}c (target ~10c)")

    def test_estimate_kling_t2v_unchanged(self, auth_headers):
        """kling T2V: 2 scenes * 50c + 2 compose = ~102c (i2v path not touched)."""
        r = requests.post(
            f"{BASE_URL}/api/studio/render/estimate",
            json=_render_payload("kling", n_scenes=2),
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        cost = r.json()["estimated_cost_cents"]
        # 100 + 2 = 102. Allow 95..115
        assert 95 <= cost <= 115, f"kling T2V estimate {cost}c not near 100-102c"
        print(f"[OK] kling t2v estimate = {cost}c (target ~100c)")

    def test_estimate_veo3_unchanged(self, auth_headers):
        """Sanity: veo3 still works after i2v changes."""
        r = requests.post(
            f"{BASE_URL}/api/studio/render/estimate",
            json=_render_payload("veo3", n_scenes=2),
            headers=auth_headers,
            timeout=20,
        )
        assert r.status_code == 200
        cost = r.json()["estimated_cost_cents"]
        assert cost > 100, f"veo3 expected >100c, got {cost}"


# ----------------------------------------------------------------------------
# 2) Constants & code-structure sanity (direct server module import)
# ----------------------------------------------------------------------------
class TestServerConstants:
    def test_kling_i2v_constants_and_model_id(self):
        # Avoid full server boot (it tries to connect to mongo on import)
        # by reading the file directly.
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        assert "KLING_I2V_COST_CENTS_5S = 25" in src, "constant missing"
        assert "KLING_I2V_MODEL = \"fal-ai/kling-video/v2.1/standard/image-to-video\"" in src, \
            "Kling i2v model id wrong"
        assert "db.kling_i2v_cache" in src, "kling_i2v_cache collection ref missing"
        assert "_fal_kling_i2v_generate" in src
        assert "_make_i2v_clip" in src
        print("[OK] server constants + model id verified")

    def test_normalize_scene_branches_on_engine(self):
        """flux_static must use _make_kenburns_mp4; flux must use _make_i2v_clip."""
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        assert "if ai_engine == \"flux_static\":" in src, "flux_static branch missing"
        assert "_make_i2v_clip(" in src, "_make_i2v_clip not invoked"
        assert "_make_kenburns_mp4(" in src, "ken-burns fallback missing"
        print("[OK] normalize_scene engine branching present")


# ----------------------------------------------------------------------------
# 3) Render queue submission (no actual Kling call)
# ----------------------------------------------------------------------------
class TestRenderQueueSubmission:
    def test_submit_flux_render_does_not_crash(self, auth_headers):
        """Submit /api/studio/render with flux — must queue (status != failed yet)."""
        payload = _render_payload("flux", n_scenes=1, script="hi there from a test script")
        r = requests.post(
            f"{BASE_URL}/api/studio/render",
            json=payload,
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        job_id = body.get("job_id") or body.get("id")
        assert job_id, f"no job_id in response: {body}"
        # Check the render doc was created
        g = requests.get(f"{BASE_URL}/api/studio/render/{job_id}", headers=auth_headers, timeout=15)
        assert g.status_code == 200
        gb = g.json()
        # Status must be a non-empty pipeline state — render was created without crash.
        st = gb.get("status")
        assert isinstance(st, str) and st, f"missing status: {gb}"
        # ai_engine should be persisted on the render doc
        assert gb.get("ai_engine") == "flux", f"engine not persisted: {gb.get('ai_engine')}"
        print(f"[OK] flux render queued status={st} ai_engine={gb.get('ai_engine')}")

    def test_submit_flux_static_render_does_not_crash(self, auth_headers):
        payload = _render_payload("flux_static", n_scenes=1, script="hi there test flux static")
        r = requests.post(
            f"{BASE_URL}/api/studio/render",
            json=payload,
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        job_id = body.get("job_id") or body.get("id")
        assert job_id
        g = requests.get(f"{BASE_URL}/api/studio/render/{job_id}", headers=auth_headers, timeout=15)
        assert g.status_code == 200
        gb = g.json()
        # ai_engine field should be persisted
        if "ai_engine" in gb:
            assert gb["ai_engine"] == "flux_static", f"engine not persisted: {gb.get('ai_engine')}"
        print(f"[OK] flux_static render queued status={gb.get('status')} engine={gb.get('ai_engine')}")


# ----------------------------------------------------------------------------
# 4) Cache write path — stub _fal_kling_i2v_generate, assert cache document
# ----------------------------------------------------------------------------
class TestKlingI2VCacheWrite:
    def test_make_i2v_clip_writes_cache_on_success(self):
        """Stub the FAL call to return a fake URL and assert the cache doc lands.
        This tests _make_i2v_clip directly so we don't pay for a real generation."""
        # Lazy import to avoid module-level side effects until needed.
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")

        import server as srv  # type: ignore

        async def runner():
            fake_url = "https://fake-fal-output.com/kling_test.mp4"
            cache_key_prefix = "kling_i2v:"
            test_image = f"https://example.com/flux_test_{int(time.time())}.png"

            # Patch the FAL call AND the trim step (the trim posts to fal as well)
            with patch.object(srv, "_fal_kling_i2v_generate", new=AsyncMock(return_value=fake_url)) as mock_gen, \
                 patch.object(srv, "_trim_t2v_clip", new=AsyncMock(return_value="https://fake-trimmed.mp4")) as mock_trim:
                result = await srv._make_i2v_clip(
                    image_url=test_image,
                    prompt="a cat dancing",
                    aspect="9_16",
                    duration_ms=4000,
                    scene_idx=0,
                )
                # Returned MP4 should be the (mocked) trimmed URL
                assert result == "https://fake-trimmed.mp4", f"got {result}"
                mock_gen.assert_called_once()
                # Verify cache write
                import hashlib
                expected_key = cache_key_prefix + hashlib.sha256(
                    f"{test_image}|9_16|5".encode("utf-8")
                ).hexdigest()[:32]
                doc = await srv.db.kling_i2v_cache.find_one({"_id": expected_key})
                assert doc is not None, f"cache doc not written for key {expected_key}"
                assert doc.get("raw_url") == fake_url
                assert doc.get("aspect") == "9_16"
                assert doc.get("duration_bucket") == "5"
                # Cleanup
                await srv.db.kling_i2v_cache.delete_one({"_id": expected_key})
                print(f"[OK] cache write verified key={expected_key[:40]}…")

        asyncio.get_event_loop().run_until_complete(runner())

    def test_make_i2v_clip_cache_hit_skips_fal_call(self):
        """If a cache entry exists, _make_i2v_clip must NOT call FAL again."""
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")
        import server as srv  # type: ignore

        async def runner():
            import hashlib
            from datetime import datetime, timezone
            test_image = f"https://example.com/flux_cached_{int(time.time())}.png"
            duration_bucket = "5"
            cache_key = "kling_i2v:" + hashlib.sha256(
                f"{test_image}|9_16|{duration_bucket}".encode("utf-8")
            ).hexdigest()[:32]
            cached_raw = "https://fake-precached.mp4"
            await srv.db.kling_i2v_cache.update_one(
                {"_id": cache_key},
                {"$set": {
                    "raw_url": cached_raw,
                    "image_url": test_image,
                    "aspect": "9_16",
                    "duration_bucket": duration_bucket,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            with patch.object(srv, "_fal_kling_i2v_generate", new=AsyncMock(return_value=None)) as mock_gen, \
                 patch.object(srv, "_trim_t2v_clip", new=AsyncMock(return_value="https://trimmed-from-cache.mp4")):
                result = await srv._make_i2v_clip(
                    image_url=test_image,
                    prompt="any",
                    aspect="9_16",
                    duration_ms=4000,
                    scene_idx=0,
                )
                # Returns trimmed url, and FAL was NOT called
                assert result == "https://trimmed-from-cache.mp4"
                mock_gen.assert_not_called()
                print("[OK] cache hit path skipped FAL call")
            # cleanup
            await srv.db.kling_i2v_cache.delete_one({"_id": cache_key})

        asyncio.get_event_loop().run_until_complete(runner())
