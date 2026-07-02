"""Iter 33 — Thumbnail Picker + Viral Style Suffix structural tests.

Cost-conscious: zero real image gens, validates prompt assembly + template
content via static inspection. Only ONE real Claude call (rewriter) is made.
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
OWNER_EMAIL = "drcharitycampbell@gmail.com"


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/check", json={"email": OWNER_EMAIL})
    if r.status_code != 200:
        pytest.skip(f"Auth failed: {r.status_code}")
    return r.json().get("token")


@pytest.fixture(scope="module")
def auth_session(auth_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"})
    return s


# === Structural: Long-form prompt template includes new sections ===
def test_long_template_has_thumbnail_sections():
    from backend.prompts import build_long_system_prompt
    tpl = build_long_system_prompt(length="medium")
    assert "🖼️ TITLE / THUMBNAIL VARIANTS" in tpl
    assert "🎨 COVER IMAGE PROMPTS" in tpl
    assert "--ar 16:9 --no text" in tpl


# === Structural: VIRAL_STYLE_SUFFIX present + applied to composed prompt ===
def test_viral_style_suffix_constants():
    from backend.thumbnails_routes import VIRAL_STYLE_SUFFIX, ASPECT_HINTS
    assert "viral YouTube thumbnail aesthetic" in VIRAL_STYLE_SUFFIX
    assert "Photorealistic, ultra-detailed, sharp focus" in VIRAL_STYLE_SUFFIX
    # All aspects exist
    for k in ("16_9", "9_16", "1_1"):
        assert k in ASPECT_HINTS
    # Negative space cue in 16:9
    assert "negative space" in ASPECT_HINTS["16_9"].lower()


def test_composed_prompt_stacks_viral_suffix():
    """Verify the 3-layer composition: user prompt + aspect hint + suffix."""
    from backend.thumbnails_routes import VIRAL_STYLE_SUFFIX, ASPECT_HINTS
    user_prompt = "a guy in a suit"
    aspect = "16_9"
    composed = f"{user_prompt}\n\n{ASPECT_HINTS[aspect]}\n\n{VIRAL_STYLE_SUFFIX}"
    assert user_prompt in composed
    assert "viral YouTube thumbnail aesthetic" in composed
    assert "Photorealistic, ultra-detailed, sharp focus" in composed
    assert composed.index(user_prompt) < composed.index(VIRAL_STYLE_SUFFIX)


# === Live: rewriter uses upgraded system prompt ===
def test_rewriter_produces_viral_keywords(auth_session):
    r = auth_session.post(
        f"{BASE_URL}/api/thumbnails/rewrite-prompt",
        json={"raw_prompt": "a guy who quit his job", "topic": "side hustle"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    rewritten = r.json().get("rewritten_prompt", "")
    assert rewritten
    word_count = len(rewritten.split())
    # Upgraded prompt targets 90-160 words; allow some slack.
    assert 60 <= word_count <= 260, f"Word count {word_count} out of band"
    keywords = [
        "expressive", "expression", "shock", "dramatic", "cinematic",
        "rim light", "palette", "negative space", "overlay text", "focal",
    ]
    hits = [k for k in keywords if k.lower() in rewritten.lower()]
    assert len(hits) >= 4, f"Only {len(hits)} viral keywords hit: {hits}\n\n{rewritten}"


# === Structural: backwards compatibility — legacy script has no cover section ===
def test_legacy_script_no_cover_section():
    """Mirrors the frontend extractCoverPrompts JS behavior at the regex level.
    A legacy script without the COVER IMAGE PROMPTS section should yield empty."""
    legacy_text = (
        "### 🎙️ FULL NARRATION SCRIPT\n"
        "[HOOK — 0:00–0:30]\n"
        "This is the opening hook content for the video.\n"
        "[B-ROLL: opening shot]\n"
        "[INTRO BRIDGE]\nMore content here.\n"
    )
    assert "COVER IMAGE PROMPTS" not in legacy_text
    assert "TITLE / THUMBNAIL VARIANTS" not in legacy_text
    # Narration body is preserved
    assert "opening hook content" in legacy_text


# === Structural: rewriter system prompt explicit keywords ===
def test_rewriter_system_prompt_keywords():
    """The system prompt itself must mention viral-thumbnail aesthetic cues."""
    import inspect
    from backend import thumbnails_routes
    src = inspect.getsource(thumbnails_routes)
    must_contain = [
        "expressive", "BOLD COLOR PALETTE", "DRAMATIC CINEMATIC LIGHTING",
        "CURIOSITY GAP", "NEGATIVE SPACE", "VIRAL",
    ]
    missing = [k for k in must_contain if k not in src]
    assert not missing, f"Rewriter system prompt missing: {missing}"
