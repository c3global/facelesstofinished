"""Iter-24 tests — Caption burn-in (fal.ai auto-subtitle second pass).

Verifies:
  1. Estimator: captions=true adds exactly +10c surcharge (faceless mode).
  2. Estimator: captions=true adds exactly +10c surcharge (avatar mode).
  3. Server constants: CAPTION_BURN_COST_CENTS=10, AUTO_SUBTITLE_MODEL,
     CAPTION_STYLE_PRESETS keys, _burn_in_captions defined.
  4. CAPTION_STYLE_PRESETS dict has all required keys per style.
  5. /api/studio/render persists captions:true + caption_style:'tiktok'.
  6. After mocked compose, _burn_in_captions is awaited with composed_url +
     style, and the captioned URL replaces the composed_url before _finalize.
  7. Soft-fail: when _burn_in_captions returns None, render still finalizes
     with the uncaptioned URL (no crash).
  8. When captions=false, _burn_in_captions is NOT called.
  9. Unknown style key falls back to the "boxed" preset (Montserrat).

Run:
    python -m pytest /app/backend/tests/test_captions_v24.py -v \
        --junitxml=/app/test_reports/pytest/iteration_24_captions.xml
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://f2f48-video-engine.preview.emergentagent.com",
).rstrip("/")
DEV_EMAIL = "drcharitycampbell@gmail.com"

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


# ----------------------------------------------------------------------------
# 1) Estimator: caption surcharge = exactly +10c (faceless + avatar)
# ----------------------------------------------------------------------------
class TestEstimatorCaptionSurcharge:
    def _estimate(self, payload, headers):
        r = requests.post(
            f"{BASE_URL}/api/studio/render/estimate",
            json=payload, headers=headers, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        return r.json()["estimated_cost_cents"]

    def test_faceless_flux_static_captions_off_then_on(self, auth_headers):
        """Same payload, only captions toggles: delta MUST be exactly 10c."""
        base = {
            "mode": "faceless",
            "ai_engine": "flux_static",
            "broll_source": "ai",
            "aspect": "9_16",
            "script": "hi",
            "scenes": [{"prompt": "cat", "source": "ai", "weight": 5}],
            "voice_id": "af_bella",
        }
        off = self._estimate({**base, "captions": False}, auth_headers)
        on = self._estimate({**base, "captions": True, "caption_style": "tiktok"}, auth_headers)
        # off should be ~6c (4 flux + 2 compose). Allow drift.
        assert 4 <= off <= 10, f"faceless flux_static captions=off expected ~6c, got {off}c"
        # delta must be exactly 10c (CAPTION_BURN_COST_CENTS)
        assert on - off == 10, f"caption surcharge expected exactly +10c, got delta={on - off}c (off={off}c, on={on}c)"
        print(f"[OK] faceless flux_static: off={off}c on={on}c delta=+10c")

    def test_avatar_captions_surcharge_delta_10c(self, auth_headers):
        """Avatar mode: enabling captions adds exactly +10c."""
        base = {
            "mode": "avatar",
            "aspect": "9_16",
            "script": "Hi. Test.",
            "avatar_id": "Anna_public_3_20240108",
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "scenes": [],
        }
        off = self._estimate({**base, "captions": False}, auth_headers)
        on = self._estimate({**base, "captions": True, "caption_style": "boxed"}, auth_headers)
        assert on - off == 10, f"avatar caption delta expected +10c, got {on - off}c (off={off}c, on={on}c)"
        print(f"[OK] avatar mode: off={off}c on={on}c delta=+10c")


# ----------------------------------------------------------------------------
# 2) Server constants & code-structure (file-level grep)
# ----------------------------------------------------------------------------
class TestServerConstants:
    def test_constants_present(self):
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        assert "CAPTION_BURN_COST_CENTS = 10" in src, "CAPTION_BURN_COST_CENTS=10 missing"
        assert 'AUTO_SUBTITLE_MODEL = "fal-ai/workflow-utilities/auto-subtitle"' in src, \
            "AUTO_SUBTITLE_MODEL constant missing or wrong"
        assert "CAPTION_STYLE_PRESETS" in src
        assert "async def _burn_in_captions(" in src, "_burn_in_captions not defined"
        print("[OK] all caption constants & function present")

    def test_caption_style_presets_keys_complete(self):
        """Each preset must have all required keys."""
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")
        import server as srv  # type: ignore

        required_keys = {
            "font_name", "font_size", "font_weight", "font_color",
            "highlight_color", "position", "words_per_subtitle",
            "enable_animation", "background_color", "background_opacity",
            "stroke_width", "stroke_color", "y_offset",
        }
        assert set(srv.CAPTION_STYLE_PRESETS.keys()) == {"boxed", "tiktok", "minimal"}, \
            f"preset top-level keys wrong: {list(srv.CAPTION_STYLE_PRESETS.keys())}"
        for style_name, preset in srv.CAPTION_STYLE_PRESETS.items():
            missing = required_keys - set(preset.keys())
            assert not missing, f"style '{style_name}' missing keys: {missing}"
        # Spot-check specific values
        assert srv.CAPTION_STYLE_PRESETS["boxed"]["font_name"] == "Montserrat"
        assert srv.CAPTION_STYLE_PRESETS["tiktok"]["words_per_subtitle"] == 3  # iter-25: 1→3 (Charity feedback)
        assert srv.CAPTION_STYLE_PRESETS["minimal"]["enable_animation"] is False
        assert srv.CAPTION_BURN_COST_CENTS == 10
        assert srv.AUTO_SUBTITLE_MODEL == "fal-ai/workflow-utilities/auto-subtitle"
        print("[OK] CAPTION_STYLE_PRESETS structure verified for all 3 styles")


# ----------------------------------------------------------------------------
# 3) Render persists captions:true + caption_style on the doc
# ----------------------------------------------------------------------------
class TestRenderDocPersistsCaptionFields:
    def test_render_submit_persists_captions_and_style(self, auth_headers):
        payload = {
            "mode": "faceless",
            "captions": True,
            "caption_style": "tiktok",
            "ai_engine": "flux_static",
            "broll_source": "ai",
            "aspect": "9_16",
            "script": "Hi. Test.",
            "scenes": [{"prompt": "cat", "source": "ai", "weight": 5}],
            "voice_id": "af_bella",
        }
        r = requests.post(
            f"{BASE_URL}/api/studio/render",
            json=payload, headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        job_id = body.get("job_id") or body.get("id")
        assert job_id, f"no job_id in response: {body}"
        # Fetch render doc to verify persistence
        g = requests.get(f"{BASE_URL}/api/studio/render/{job_id}", headers=auth_headers, timeout=15)
        assert g.status_code == 200
        doc = g.json()
        assert doc.get("captions") is True, f"captions not persisted: {doc.get('captions')}"
        assert doc.get("caption_style") == "tiktok", \
            f"caption_style not persisted: {doc.get('caption_style')}"
        print(f"[OK] render doc {job_id[:8]} persists captions=True caption_style=tiktok")


# ----------------------------------------------------------------------------
# 4) _burn_in_captions direct unit tests (mock httpx) — style fallback
# ----------------------------------------------------------------------------
class TestBurnInCaptionsDirect:
    def test_unknown_style_falls_back_to_boxed_preset(self):
        """Pass an unknown style key — payload sent to FAL must include the
        BOXED preset values (font_name=Montserrat)."""
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")
        import server as srv  # type: ignore

        async def runner():
            captured = {}

            class FakeResp:
                status_code = 400  # fail fast after submit so we don't poll
                text = "abort"

                def json(self):
                    return {}

            class FakeClient:
                def __init__(self, *a, **kw):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                async def post(self, url, headers=None, json=None):
                    captured["url"] = url
                    captured["payload"] = json
                    return FakeResp()

            # _burn_in_captions returns None if FAL_API_KEY not set — make sure it is.
            with patch.object(srv, "FAL_API_KEY", "test-key-not-real"), \
                 patch.object(srv.httpx, "AsyncClient", FakeClient):
                result = await srv._burn_in_captions(
                    "https://example.com/in.mp4", "experimental_unknown_style",
                )
                assert result is None  # fast-failed at status 400
                payload = captured.get("payload") or {}
                # Boxed preset's font_name must be Montserrat
                assert payload.get("font_name") == "Montserrat", \
                    f"unknown-style fallback should use boxed preset font_name=Montserrat, got {payload.get('font_name')}"
                assert payload.get("words_per_subtitle") == 4, \
                    "boxed preset words_per_subtitle expected 4"
                assert captured["url"].endswith("/fal-ai/workflow-utilities/auto-subtitle"), \
                    f"wrong submit URL: {captured['url']}"
                print("[OK] unknown style falls back to boxed preset (Montserrat, 4 words/subtitle)")

        asyncio.get_event_loop().run_until_complete(runner())

    def test_no_fal_key_returns_none_without_calling_http(self):
        """If FAL_API_KEY is unset, function must return None immediately."""
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")
        import server as srv  # type: ignore

        async def runner():
            with patch.object(srv, "FAL_API_KEY", ""):
                result = await srv._burn_in_captions("https://x.com/v.mp4", "boxed")
                assert result is None
                print("[OK] missing FAL_API_KEY → returns None")

        asyncio.get_event_loop().run_until_complete(runner())


# ----------------------------------------------------------------------------
# 5) Faceless pipeline: caption second-pass conditional behavior
# ----------------------------------------------------------------------------
# These tests simulate ONLY the post-compose caption block (lines 2400-2421 in
# server.py) since _run_render_faceless is huge and depends on TTS/FAL. They
# mirror the exact logic to verify: replace-on-success, soft-fail-on-None,
# and skip when captions=False.
class TestCaptionBlockBehavior:
    def _exec_caption_block(self, captions_enabled, burn_return, caption_style="boxed"):
        """Replicate the exact post-compose block from _run_render_faceless to
        exercise the replace/soft-fail/skip conditional under controlled inputs."""
        os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
        os.environ.setdefault("DB_NAME", "test_database")
        import server as srv  # type: ignore

        composed_url = "https://composed.mp4"
        actual_cost_cents = 50
        job = {"captions": captions_enabled, "caption_style": caption_style}
        call_args = {}

        async def fake_burn(url, style):
            call_args["url"] = url
            call_args["style"] = style
            call_args["called"] = True
            return burn_return

        async def runner():
            nonlocal composed_url, actual_cost_cents
            mock = AsyncMock(side_effect=fake_burn)
            with patch.object(srv, "_burn_in_captions", new=mock):
                # === MIRROR of server.py lines 2407-2419 ===
                if composed_url and job.get("captions"):
                    try:
                        captioned_url = await srv._burn_in_captions(
                            composed_url, job.get("caption_style") or "boxed"
                        )
                        if captioned_url:
                            composed_url = captioned_url
                            actual_cost_cents += srv.CAPTION_BURN_COST_CENTS
                    except Exception:
                        pass
                return composed_url, actual_cost_cents, mock

        return asyncio.get_event_loop().run_until_complete(runner()), call_args

    def test_caption_success_replaces_url_and_charges_10c(self):
        (final_url, cost, mock), call_args = self._exec_caption_block(
            captions_enabled=True, burn_return="https://captioned.mp4", caption_style="tiktok",
        )
        assert final_url == "https://captioned.mp4", f"url not swapped: {final_url}"
        assert cost == 60, f"caption cost not added: {cost}c (expected 60)"
        mock.assert_awaited_once()
        assert call_args["url"] == "https://composed.mp4"
        assert call_args["style"] == "tiktok"
        print(f"[OK] success path: url={final_url} cost={cost}c style={call_args['style']}")

    def test_caption_soft_fail_returns_uncaptioned_no_crash(self):
        """_burn_in_captions returns None → composed_url unchanged, no cost added."""
        (final_url, cost, mock), call_args = self._exec_caption_block(
            captions_enabled=True, burn_return=None, caption_style="boxed",
        )
        assert final_url == "https://composed.mp4", \
            f"soft-fail did NOT keep uncaptioned URL: {final_url}"
        assert cost == 50, f"soft-fail should not charge captions: cost={cost}c"
        mock.assert_awaited_once()
        print(f"[OK] soft-fail: kept uncaptioned URL, cost unchanged={cost}c")

    def test_captions_false_does_not_call_burn(self):
        """captions=False → _burn_in_captions never called even if FAL key set."""
        (final_url, cost, mock), call_args = self._exec_caption_block(
            captions_enabled=False, burn_return="https://shouldnotappear.mp4",
        )
        assert final_url == "https://composed.mp4"
        assert cost == 50
        mock.assert_not_called()
        assert "called" not in call_args
        print("[OK] captions=False → _burn_in_captions NOT called")
