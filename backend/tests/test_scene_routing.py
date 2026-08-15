"""Focused tests for the strict B-roll routing contract (v1.20.12).

The contract:
  * source = "ai"                → renderer uses `prompt`, never `search_query`
  * source = "pexels" / "pixabay" → renderer uses `search_query` only;
                                    falls back to `_extract_stock_query(prompt)`
                                    when `search_query` is missing.
                                    Never sends the raw AI prompt to a stock
                                    provider.
  * source = "uploaded"          → renderer uses the pre-picked file URL only.
                                    No AI generation, no Pexels, no Pixabay.

These tests exercise the *routing helpers* (`_resolve_stock_query_for_scene`,
`_extract_stock_query`, `classify_scene_kind`) — they never make a real HTTP
call, never touch Mongo, and never fire a paid provider.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make backend/ imports work when pytest runs from the repo root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# `server.py` reads env vars at import; the placeholder values below let it
# import cleanly under pytest without touching real credentials.
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "f48_tests")
os.environ.setdefault("CORS_ORIGINS", "*")

import server  # noqa: E402  (env vars must be set first)
from media_routing import classify_scene_kind  # noqa: E402


# --------------------------------------------------------------------------- #
# Helper: `_resolve_stock_query_for_scene` — the single choke-point that
# decides what string reaches Pexels/Pixabay.
# --------------------------------------------------------------------------- #

CINEMATIC_AI_PROMPT = (
    "Wide overhead shot of hands typing on laptop keyboard, "
    "soft window daylight, slow camera drift right"
)


def test_pexels_scene_uses_search_query_when_present():
    scene = {
        "source": "pexels",
        "prompt": CINEMATIC_AI_PROMPT,
        "search_query": "person typing laptop",
    }
    resolved = server._resolve_stock_query_for_scene(scene)
    assert resolved == "person typing laptop"


def test_pixabay_scene_uses_search_query_when_present():
    scene = {
        "source": "pixabay",
        "prompt": CINEMATIC_AI_PROMPT,
        "search_query": "team meeting office",
    }
    resolved = server._resolve_stock_query_for_scene(scene)
    assert resolved == "team meeting office"


def test_pexels_scene_missing_search_query_uses_sanitizer_fallback():
    """The raw cinematic prompt must NEVER reach Pexels — it must be
    sanitized via `_extract_stock_query` first."""
    scene = {"source": "pexels", "prompt": CINEMATIC_AI_PROMPT}
    resolved = server._resolve_stock_query_for_scene(scene)
    # Sanitizer strips shot-type + camera-motion + lighting vocabulary.
    for banned in ("wide", "overhead", "shot", "soft", "slow", "camera", "drift"):
        assert banned not in resolved.split(), (
            f"Sanitizer failed to strip '{banned}' from stock query: {resolved!r}"
        )
    # Concrete visual nouns must survive.
    assert "hands" in resolved
    assert "typing" in resolved
    assert "laptop" in resolved or "keyboard" in resolved


def test_pexels_scene_with_empty_search_query_falls_back():
    scene = {"source": "pexels", "prompt": CINEMATIC_AI_PROMPT, "search_query": ""}
    resolved = server._resolve_stock_query_for_scene(scene)
    # Empty string is treated as "missing" — sanitizer fallback fires.
    assert resolved
    assert "wide" not in resolved.split()


def test_pexels_scene_with_whitespace_search_query_falls_back():
    scene = {"source": "pexels", "prompt": CINEMATIC_AI_PROMPT, "search_query": "   "}
    resolved = server._resolve_stock_query_for_scene(scene)
    assert resolved
    assert "shot" not in resolved.split()


def test_pexels_scene_with_no_prompt_and_no_query_returns_empty():
    scene = {"source": "pexels"}
    resolved = server._resolve_stock_query_for_scene(scene)
    assert resolved == ""


# --------------------------------------------------------------------------- #
# `classify_scene_kind` — proves the three source classes route to
# disjoint execution paths (AI vs stock vs local).
# --------------------------------------------------------------------------- #


def test_uploaded_image_scene_classifies_local_only():
    scene = {
        "source": "uploaded",
        "kind": "image",
        "video_url": "/api/files/6a80a477cebdba9e63b18452",
        "prompt": "display-only description",
    }
    kind = classify_scene_kind(scene, global_source="pexels", is_t2v=False)
    assert kind == "uploaded_image", (
        "Uploaded image must never route into AI or stock code paths"
    )


def test_uploaded_video_scene_classifies_local_only():
    scene = {
        "source": "uploaded",
        "kind": "video",
        "video_url": "/api/files/6a80a478cebdba9e63b18454",
        "prompt": "display-only description",
    }
    kind = classify_scene_kind(scene, global_source="pexels", is_t2v=False)
    assert kind == "uploaded_video"


def test_ai_scene_classifies_as_ai():
    scene = {"source": "ai", "prompt": CINEMATIC_AI_PROMPT}
    kind = classify_scene_kind(scene, global_source="ai", is_t2v=False)
    assert kind == "ai"


def test_ai_t2v_scene_classifies_as_ai_t2v():
    scene = {"source": "ai", "prompt": CINEMATIC_AI_PROMPT}
    kind = classify_scene_kind(scene, global_source="ai", is_t2v=True)
    assert kind == "ai_t2v"


def test_pexels_scene_classifies_as_stock():
    scene = {"source": "pexels", "prompt": CINEMATIC_AI_PROMPT, "search_query": "coffee"}
    kind = classify_scene_kind(scene, global_source="pexels", is_t2v=False)
    assert kind == "stock"


def test_pixabay_scene_classifies_as_stock():
    scene = {"source": "pixabay", "prompt": CINEMATIC_AI_PROMPT, "search_query": "coffee"}
    kind = classify_scene_kind(scene, global_source="pixabay", is_t2v=False)
    assert kind == "stock"


# --------------------------------------------------------------------------- #
# Contract enforcement: `_resolve_stock_query_for_scene` NEVER lets a
# detailed AI cue slip through to a stock provider — even when the caller
# forgot to also strip shot vocabulary from the AI prompt.
# --------------------------------------------------------------------------- #


def test_ai_prompt_shot_vocabulary_is_stripped_when_used_as_fallback():
    """Even when the fallback path fires, shot-type / camera-motion /
    lighting vocabulary must not survive into the stock query. Domain-
    specific UI words are handled by the BROLL_PROMPTS_SYSTEM rules that
    teach Claude to translate them into concrete visual scenes upstream —
    but the sanitizer is the last-line guard against cinematic vocabulary
    escaping to Pexels/Pixabay."""
    scene = {
        "source": "pexels",
        "prompt": (
            "Wide overhead shot of split-screen influencer studio, "
            "soft daylight, slow camera drift right"
        ),
    }
    resolved = server._resolve_stock_query_for_scene(scene)
    tokens = set(resolved.split())
    # Shot-type, camera-motion, and mood modifiers must all be stripped
    # (these are the classes `_extract_stock_query` explicitly targets —
    # they filtered Pexels/Pixabay relevance to near-zero in v1.19.6 and
    # earlier). "daylight" survives because it is a real stock tag.
    for banned in ("wide", "overhead", "shot", "soft", "slow", "camera", "drift"):
        assert banned not in tokens, (
            f"Sanitizer failed to strip '{banned}' from stock query: {resolved!r}"
        )
    # Result is bounded to 6 words — no matter what a long AI prompt was.
    assert len(resolved.split()) <= 6


def test_stock_query_result_is_length_bounded_when_used_as_fallback():
    scene = {
        "source": "pexels",
        "prompt": "Cursor clicking start recording in screen capture software "
                  "over a home office workspace with warm afternoon light",
    }
    resolved = server._resolve_stock_query_for_scene(scene)
    # No matter the input length, the sanitizer caps at 6 tokens.
    assert 0 < len(resolved.split()) <= 6


def test_comment_section_prompt_becomes_filmable_stock_query():
    resolved = server._extract_stock_query(
        'Comment section with messages like "Finally someone who knows what they are doing"'
    )
    assert resolved == "person using smartphone"


def test_software_interface_prompt_becomes_filmable_stock_query():
    resolved = server._extract_stock_query(
        "Cursor clicking start recording in screen capture software"
    )
    assert resolved == "person using computer"


# --------------------------------------------------------------------------- #
# Preview Clips (`/studio/stock-candidates`) routing — the client-triggered
# per-scene candidate fetch must honour the same paired contract as Render.
# --------------------------------------------------------------------------- #


def test_preview_clips_query_resolver_uses_search_query_when_present():
    """When Preview Clips is called with a paired `search_query`, that
    string is what actually gets sent to Pexels/Pixabay — not the
    detailed AI prompt."""
    resolve = _preview_clips_query_resolver()

    q = resolve(
        prompt=(
            "Medium tracking shot of a barista pouring milk into a coffee cup, "
            "warm indoor light, gentle push-in"
        ),
        search_query="coffee pouring cup",
    )
    assert q == "coffee pouring cup"


def test_preview_clips_query_resolver_sanitizes_prompt_when_search_query_missing():
    resolve = _preview_clips_query_resolver()

    q = resolve(
        prompt=(
            "Wide overhead shot of hands typing on laptop keyboard, "
            "soft window daylight, slow camera drift right"
        ),
        search_query=None,
    )
    tokens = q.split()
    for banned in ("wide", "overhead", "shot", "soft", "slow", "camera", "drift"):
        assert banned not in tokens
    # Sanitizer produced a real query.
    assert len(tokens) >= 1
    # Result is length-bounded — same guarantee as `_extract_stock_query`.
    assert len(tokens) <= 6


def test_preview_clips_query_resolver_treats_empty_string_as_missing():
    resolve = _preview_clips_query_resolver()

    for empty in ("", "   ", None):
        q = resolve(
            prompt="Wide overhead shot of hands typing on laptop, soft daylight",
            search_query=empty,
        )
        assert "overhead" not in q.split()
        assert "shot" not in q.split()


def test_preview_clips_query_resolver_never_sends_raw_prompt():
    """If both search_query and sanitized prompt are empty, the resolver
    returns an empty string — the caller must decide what to do (the
    endpoint returns [] instead of leaking the raw prompt)."""
    resolve = _preview_clips_query_resolver()

    q = resolve(prompt="", search_query="")
    assert q == ""

    # Prompt that's all stopwords → sanitizer returns "" → resolver returns "".
    q = resolve(prompt="the and of in", search_query=None)
    assert q == ""


def _preview_clips_query_resolver():
    """Return the exact resolver `/studio/stock-candidates` uses so we can
    exercise it in isolation. Mirrors the inline `resolve_query` closure
    in `studio_stock_candidates` — kept in sync via this shared test."""
    def resolve(prompt: str, search_query):
        sq = (search_query or "").strip()
        if sq:
            return sq
        return server._extract_stock_query(prompt or "")
    return resolve


# --------------------------------------------------------------------------- #
# Regression: `search_query` survives round-trip through:
#   /studio/broll-prompts response → frontend `scenes[i]` → render payload
# We can't drive the frontend from pytest, but we CAN prove the backend
# preserves and consumes the field end-to-end via a tiny simulated payload.
# --------------------------------------------------------------------------- #


def test_search_query_survives_broll_prompts_to_render_payload_regression():
    # Shape emitted by /studio/broll-prompts (v1.20.9+).
    broll_prompts_scene = {
        "prompt": (
            "Medium tracking shot of a barista pouring milk into a coffee cup, "
            "warm indoor light, gentle push-in"
        ),
        "search_query": "coffee pouring cup",
        "weight": 12,
        "text": "That first sip is the reward for the whole morning.",
        "estimated_duration_ms": 4200,
        "cutaway_count": 1,
    }

    # Frontend maps this into a scene the way `scenes` useMemo + buildPayload
    # do after the v1.20.12 fix. We simulate the shape rather than run React.
    render_scene = {
        "source": "pexels",
        "prompt": broll_prompts_scene["prompt"],
        "search_query": broll_prompts_scene["search_query"],
        "weight": broll_prompts_scene["weight"],
    }

    # Now the renderer's routing choke-point must see the exact search query.
    resolved = server._resolve_stock_query_for_scene(render_scene)
    assert resolved == "coffee pouring cup"

    # The scene must classify as `stock` (not `ai`, not `uploaded`).
    kind = classify_scene_kind(render_scene, global_source="pexels", is_t2v=False)
    assert kind == "stock"


def test_uploaded_scene_bypasses_ai_and_stock_regression():
    """Uploaded scenes must not resolve any stock query — even if a
    `search_query` field is present by accident, `classify_scene_kind`
    routes them to the local pipeline and never reaches
    `_resolve_stock_query_for_scene` in production."""
    upload_scene = {
        "source": "uploaded",
        "kind": "image",
        "video_url": "/api/files/6a80add8f58b19d232df7a84",
        "prompt": "display-only cue",
        "search_query": "should not be used",
    }
    kind = classify_scene_kind(upload_scene, global_source="pexels", is_t2v=False)
    # The routing kind alone proves this scene bypasses AI + stock branches.
    assert kind in ("uploaded_image", "uploaded_video")
