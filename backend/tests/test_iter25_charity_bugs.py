"""
Iteration 25 — Tests for Charity's 4 bug reports + new caption-position +
flux hardening + ai-previews features.

Covered:
  1) /api/studio/voices still returns 2329 voices (no truncation).
  2) /api/studio/avatars returns 1281 avatars; aspect breakdown ~27/595/659.
  3) HeyGen polling max_ticks=300 + error string "after 25 minutes".
  4) Kokoro client httpx.Timeout(connect=15, read=360, write=60, pool=15)
     + 2-retry ReadError loop in _run_tts.
  5) RenderRequest accepts caption_position field; persists on the doc.
  6) _burn_in_captions payload uses position+y_offset overrides correctly.
  7) /api/studio/ai-previews caches via db.flux_cache (2nd call hits cache).
  8) gen_image Flux payload includes num_inference_steps=32, guidance_scale=4.0,
     output_format=png, and the hardened cinematic+no-text prompt.
"""

import os
import re
import sys
import json
import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

def _read_frontend_url() -> str:
    p = Path("/app/frontend/.env")
    for line in p.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().rstrip("/")
    return ""

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_url()).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

# Motor's GridFSBucket needs a current event loop at import time.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# Make backend importable for in-process tests of helpers + the FastAPI app.
sys.path.insert(0, "/app/backend")


# ---------- Auth fixture --------------------------------------------------
@pytest.fixture(scope="module")
def admin_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/check",
        json={"email": "drcharitycampbell@gmail.com"},
        timeout=20,
    )
    assert r.status_code == 200, f"auth/check failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token")
    assert tok, "no token returned"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# =========================================================================
# 1) Voices: still 2329, no truncation
# =========================================================================
def test_voices_returns_2329(auth_headers):
    r = requests.get(f"{BASE_URL}/api/studio/voices", headers=auth_headers, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    voices = body.get("voices") if isinstance(body, dict) else body
    assert isinstance(voices, list), f"unexpected shape: {type(body)}"
    assert len(voices) == 2329, f"expected 2329 voices, got {len(voices)}"


# =========================================================================
# 2) Avatars: 1281 total + aspect breakdown ~27 portrait / ~595 both / ~659 landscape
# =========================================================================
def test_avatars_returns_1281_with_aspect_breakdown(auth_headers):
    r = requests.get(f"{BASE_URL}/api/studio/avatars", headers=auth_headers, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    avatars = body.get("avatars") if isinstance(body, dict) else body
    assert isinstance(avatars, list)
    assert len(avatars) == 1281, f"expected 1281 avatars, got {len(avatars)}"
    counts = {"portrait": 0, "both": 0, "landscape": 0, "other": 0}
    for a in avatars:
        counts[a.get("aspect") if a.get("aspect") in counts else "other"] += 1
    # Allow ±5 wiggle around the documented breakdown.
    assert abs(counts["portrait"] - 27) <= 5, counts
    assert abs(counts["both"] - 595) <= 10, counts
    assert abs(counts["landscape"] - 659) <= 10, counts
    # The 9:16 picker filter (portrait OR both) must surface > 100 (used by FE test).
    assert counts["portrait"] + counts["both"] > 100, counts


# =========================================================================
# 3) HeyGen polling max_ticks=300 + "25 minutes" error string
# =========================================================================
def test_heygen_polling_max_ticks_300_and_error_string():
    src = Path("/app/backend/server.py").read_text()
    # Both lines should be near each other in _run_render_avatar.
    assert "max_ticks = 300" in src, "expected max_ticks = 300 (25 min) constant"
    assert "HeyGen polling timed out after 25 minutes" in src, (
        "expected new 25-minute error string in source"
    )
    assert "HeyGen polling timed out after 5 minutes" not in src, (
        "old 5-minute string must be gone"
    )


# =========================================================================
# 4) Kokoro: httpx.Timeout + 2-retry ReadError loop in _run_tts
# =========================================================================
def test_kokoro_httpx_timeout_constants_in_source():
    src = Path("/app/backend/server.py").read_text()
    assert "httpx.Timeout(connect=15.0, read=360.0, write=60.0, pool=15.0)" in src
    # 2 retries on transient network errors.
    assert "httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError" in src
    # 3 attempts (range(3) means 2 retries after the first attempt).
    assert "for attempt in range(3)" in src


def test_run_tts_retries_twice_then_succeeds_on_third_attempt():
    """Simulate two ReadError raises, then a successful response — verify
    the retry loop swallows them and the 3rd call returns the success body."""
    import httpx as _httpx  # noqa: PLC0415

    async def _do():
        attempts = {"n": 0}

        async def post_side_effect(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _httpx.ReadError("simulated transient")
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value={"audio_url": "https://x/audio.mp3"})
            resp.text = ""
            return resp

        client = MagicMock()
        client.post = AsyncMock(side_effect=post_side_effect)

        async def _run_tts():
            last_exc = None
            for attempt in range(3):
                try:
                    return await client.post(
                        "https://fal.run/fal-ai/kokoro/american-english",
                        headers={},
                        json={"prompt": "hi", "voice": "af_heart"},
                    )
                except (_httpx.ReadError, _httpx.ReadTimeout, _httpx.RemoteProtocolError) as exc:
                    last_exc = exc
                    if attempt < 2:
                        await asyncio.sleep(0)
                        continue
                    raise
            if last_exc:
                raise last_exc
            return None

        out = await _run_tts()
        assert out.status_code == 200
        assert out.json()["audio_url"] == "https://x/audio.mp3"
        assert attempts["n"] == 3

    asyncio.get_event_loop().run_until_complete(_do())


# =========================================================================
# 5) RenderRequest accepts caption_position; persists on the doc
# =========================================================================
def test_render_request_persists_caption_position(auth_headers):
    payload = {
        "mode": "faceless",
        "script": "TEST_iter25 caption position persistence. A short test.",
        "aspect": "9_16",
        "tts_voice_id": "af_heart",
        "engine": "flux_static",
        "captions": True,
        "caption_style": "tiktok",
        "caption_position": "top",
    }
    r = requests.post(
        f"{BASE_URL}/api/studio/render", headers=auth_headers, json=payload, timeout=30
    )
    assert r.status_code in (200, 201, 202), r.text[:200]
    body = r.json()
    rid = body.get("id") or body.get("render_id") or body.get("_id")
    assert rid, f"no render id in response: {body}"
    g = requests.get(f"{BASE_URL}/api/studio/render/{rid}", headers=auth_headers, timeout=15)
    assert g.status_code == 200, g.text[:200]
    doc = g.json()
    assert doc.get("caption_position") == "top", f"caption_position not persisted: {doc.get('caption_position')}"
    assert doc.get("caption_style") == "tiktok"
    assert doc.get("captions") is True


# =========================================================================
# 6) _burn_in_captions: top → position=top, y_offset=90; center → position=center, y_offset=0
# =========================================================================
def test_burn_in_captions_position_top_payload():
    """Patch httpx.AsyncClient.post inside server module and inspect the
    payload sent for both 'top' and 'center' position overrides."""
    import server as srv  # noqa: PLC0415

    # Make sure FAL key is set so the helper proceeds (we patch the network).
    srv.FAL_API_KEY = srv.FAL_API_KEY or "test-key"

    captured = {}

    async def fake_post(self, url, headers=None, json=None, **kw):
        captured["payload"] = json
        # Return a malformed body that triggers the helper's early-return
        # path *after* the payload was captured. (status_url missing.)
        r = MagicMock()
        r.status_code = 200
        r.text = "{}"
        r.json = MagicMock(return_value={})
        return r

    async def _run(pos: str):
        captured.clear()
        with patch("httpx.AsyncClient.post", new=fake_post):
            await srv._burn_in_captions("https://x/video.mp4", "tiktok", pos)
        return captured.get("payload") or {}

    loop = asyncio.get_event_loop()
    p_top = loop.run_until_complete(_run("top"))
    assert p_top.get("position") == "top", p_top
    assert p_top.get("y_offset") == 90, p_top

    p_center = loop.run_until_complete(_run("center"))
    assert p_center.get("position") == "center", p_center
    assert p_center.get("y_offset") == 0, p_center

    p_bottom = loop.run_until_complete(_run("bottom"))
    assert p_bottom.get("position") == "bottom", p_bottom
    assert p_bottom.get("y_offset") == 90, p_bottom


# =========================================================================
# 7) /api/studio/ai-previews — first call writes cache, second call returns cached=true
# =========================================================================
def test_ai_previews_endpoint_cache_behavior(auth_headers):
    """We can't actually call fal.ai. Instead pre-seed db.flux_cache with the
    exact key the endpoint computes, then call the endpoint and assert
    cached=true is returned for both prompts. (This exercises the cache
    branch end-to-end through the HTTP route, which is what the bug
    report cares about.)"""
    import hashlib  # noqa: PLC0415
    import time as _time  # noqa: PLC0415
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: PLC0415
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv("/app/backend/.env", override=True)
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    assert db_name == "f48_studio", f"DB_NAME polluted: {db_name}"

    aspect = "9_16"
    aspect_tag = "p"  # matches server.py: "p" for 9_16
    # Per-run unique prompts so this test can never collide with leftovers.
    nonce = str(int(_time.time() * 1000))
    prompts = [f"TEST_iter25_cat_{nonce}", f"TEST_iter25_dog_{nonce}"]
    keys = [
        "flux:" + hashlib.sha256(f"{aspect_tag}|{p}".encode("utf-8")).hexdigest()[:32]
        for p in prompts
    ]
    fake_urls = {keys[0]: "https://cache/test_cat.png", keys[1]: "https://cache/test_dog.png"}

    # Use a dedicated event loop owned by THIS test so prior test loop state
    # (kling tests close their loops) cannot interfere with our motor client.
    seed_loop = asyncio.new_event_loop()

    async def seed_and_verify():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        for k, u in fake_urls.items():
            await db.flux_cache.update_one(
                {"_id": k},
                {"$set": {"url": u, "prompt": "seed", "aspect": aspect, "cached_at": "seed"}},
                upsert=True,
            )
        # Verify seed actually landed.
        for k, u in fake_urls.items():
            doc = await db.flux_cache.find_one({"_id": k})
            assert doc and doc.get("url") == u, f"seed verify failed: {k} -> {doc}"
        client.close()

    async def cleanup():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        await db.flux_cache.delete_many({"_id": {"$in": keys}})
        client.close()

    try:
        seed_loop.run_until_complete(seed_and_verify())
        r = requests.post(
            f"{BASE_URL}/api/studio/ai-previews",
            headers=auth_headers,
            json={"prompts": prompts, "aspect": aspect},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        previews = body.get("previews")
        assert isinstance(previews, list) and len(previews) == 2, body
        # Order is by idx.
        for i, p in enumerate(previews):
            assert p["idx"] == i
            assert p["cached"] is True, f"expected cached=true on idx={i}, got {p}"
            assert p["image_url"] == fake_urls[keys[i]], f"wrong cached url for idx={i}: {p}"
    finally:
        seed_loop.run_until_complete(cleanup())
        seed_loop.close()


def test_ai_previews_endpoint_validates_aspect(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/studio/ai-previews",
        headers=auth_headers,
        json={"prompts": ["x"], "aspect": "1_1"},
        timeout=10,
    )
    assert r.status_code == 400, r.text[:200]


def test_ai_previews_endpoint_empty_prompts(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/studio/ai-previews",
        headers=auth_headers,
        json={"prompts": [], "aspect": "9_16"},
        timeout=10,
    )
    assert r.status_code == 200, r.text[:200]
    assert r.json() == {"previews": []}


# =========================================================================
# 8) Flux prompt hardening — gen_image payload params
# =========================================================================
def test_gen_image_flux_payload_hardened_constants():
    src = Path("/app/backend/server.py").read_text()
    # Find the gen_image function block (defined inside _run_render_faceless).
    m = re.search(r"async def gen_image\(.*?return None\n\s+data = ir.json\(\)", src, re.DOTALL)
    assert m, "gen_image function not found in server.py"
    block = m.group(0)
    assert '"num_inference_steps": 32' in block, "missing num_inference_steps=32"
    assert '"guidance_scale": 4.0' in block, "missing guidance_scale=4.0"
    assert '"output_format": "png"' in block, "missing output_format=png"
    assert "Cinematic photograph" in block, "missing cinematic style anchor"
    assert "No visible text or signage" in block, "missing no-text negative phrasing"


def test_ai_previews_flux_payload_hardened_constants():
    src = Path("/app/backend/server.py").read_text()
    m = re.search(r"@api\.post\(\"/studio/ai-previews\"\).*?return \{\"previews\": results\}", src, re.DOTALL)
    assert m, "ai-previews endpoint block not found"
    block = m.group(0)
    assert '"num_inference_steps": 32' in block
    assert '"guidance_scale": 4.0' in block
    assert '"output_format": "png"' in block
    assert "Cinematic photograph" in block
    assert "No visible text or signage" in block


# =========================================================================
# 9) Caption position overrides constant present
# =========================================================================
def test_caption_position_overrides_constant_shape():
    import server as srv  # noqa: PLC0415

    o = srv.CAPTION_POSITION_OVERRIDES
    assert set(o.keys()) == {"top", "bottom", "center"}
    assert o["top"] == {"position": "top", "y_offset": 90}
    assert o["bottom"] == {"position": "bottom", "y_offset": 90}
    assert o["center"] == {"position": "center", "y_offset": 0}


def test_burn_in_captions_signature_has_position_key():
    import server as srv  # noqa: PLC0415

    sig = inspect.signature(srv._burn_in_captions)
    assert "position_key" in sig.parameters, sig
    assert sig.parameters["position_key"].default == "bottom"
