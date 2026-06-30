"""Caption burn-in pipeline — second-pass fal.ai workflow that bakes
subtitles into the rendered video.

Extracted from server.py in v1.15.0 to keep the main module smaller and
to give the captioning pipeline its own home for future style additions.

Public surface (stable — re-exported by server.py for backward compat):
    - CAPTION_STYLE_PRESETS      : style-name → fal.ai payload dict
    - CAPTION_POSITION_OVERRIDES : "top" | "bottom" | "center" overrides
    - burn_in_captions(...)      : async helper returning captioned URL or None

The helper deliberately soft-fails (returns None) on any error so the
caller can ship the uncaptioned video as a fallback instead of failing the
whole render. This is locked by /app/backend/tests/test_caption_burn_in.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)


AUTO_SUBTITLE_MODEL = "fal-ai/workflow-utilities/auto-subtitle"
CAPTION_BURN_MAX_WAIT_S = 600


CAPTION_STYLE_PRESETS: dict[str, dict] = {
    # Bold TikTok-ish bottom captions on a translucent box — the safe default.
    "boxed": {
        "font_name": "Montserrat",
        "font_size": 92,
        "font_weight": "bold",
        "font_color": "white",
        "highlight_color": "yellow",
        "stroke_width": 2,
        "stroke_color": "black",
        "background_color": "black",
        "background_opacity": 0.55,
        "position": "bottom",
        "y_offset": 90,
        "words_per_subtitle": 4,
        "enable_animation": True,
    },
    # Bold karaoke style — three words at a time, fewer than "boxed" so it
    # stays readable in the center where it overlaps the subject.
    "tiktok": {
        "font_name": "Poppins",
        "font_size": 96,
        "font_weight": "black",
        "font_color": "white",
        "highlight_color": "purple",
        "stroke_width": 4,
        "stroke_color": "black",
        "background_color": "none",
        "background_opacity": 0.0,
        "position": "bottom",   # overridden by caption_position request field
        "y_offset": 90,
        "words_per_subtitle": 3,
        "enable_animation": True,
    },
    # Minimal documentary-style captions — small, clean, no animation.
    "minimal": {
        "font_name": "Inter",
        "font_size": 64,
        "font_weight": "normal",
        "font_color": "white",
        "highlight_color": "white",
        "stroke_width": 1,
        "stroke_color": "black",
        "background_color": "none",
        "background_opacity": 0.0,
        "position": "bottom",
        "y_offset": 60,
        "words_per_subtitle": 6,
        "enable_animation": False,
    },
}


# UI lets the user override the vertical placement of the captions
# regardless of style: top / bottom (style default) / center overlay.
CAPTION_POSITION_OVERRIDES: dict[str, dict] = {
    "top":    {"position": "top",    "y_offset": 90},
    "bottom": {"position": "bottom", "y_offset": 90},
    "center": {"position": "center", "y_offset": 0},
}


async def burn_in_captions(
    video_url: str,
    style_key: str,
    position_key: str = "bottom",
    *,
    fal_key_provider: Optional[Callable[[], str]] = None,
) -> Optional[str]:
    """Second pass through fal.ai's auto-subtitle workflow. Returns the URL
    of the captioned MP4, or None on any error (caller falls back to the
    uncaptioned video).

    `fal_key_provider` is injected so the BYOK ContextVar in server.py can
    take precedence over the platform key at call-time — it's a callable
    rather than a value so the lookup happens inside the active render
    coroutine, not at module-import time.
    """
    fal_key = (fal_key_provider() if fal_key_provider else "") or ""
    if not fal_key or not video_url:
        return None

    style = dict(CAPTION_STYLE_PRESETS.get(style_key) or CAPTION_STYLE_PRESETS["boxed"])
    pos_override = CAPTION_POSITION_OVERRIDES.get(position_key)
    if pos_override:
        style.update(pos_override)

    payload = {"video_url": video_url, "language": "en", **style}
    fal_headers = {"Authorization": f"Key {fal_key}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            sub = await client.post(
                f"https://queue.fal.run/{AUTO_SUBTITLE_MODEL}",
                headers=fal_headers,
                json=payload,
            )
            if sub.status_code not in (200, 202):
                logger.warning(f"[captions] submit FAIL {sub.status_code}: {sub.text[:200]}")
                return None
            sub_body = sub.json()
            status_url = sub_body.get("status_url")
            result_url = sub_body.get("response_url")
            if not status_url or not result_url:
                logger.warning(f"[captions] submit malformed: {str(sub_body)[:200]}")
                return None
            deadline = asyncio.get_event_loop().time() + CAPTION_BURN_MAX_WAIT_S
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(2)
                stat = await client.get(status_url, headers=fal_headers)
                if stat.status_code != 200:
                    continue
                st = stat.json().get("status", "")
                if st == "COMPLETED":
                    res = await client.get(result_url, headers=fal_headers)
                    if res.status_code != 200:
                        return None
                    out = res.json()
                    return (out.get("video") or {}).get("url") or out.get("video_url")
                if st == "FAILED":
                    logger.warning(f"[captions] FAILED: {stat.text[:200]}")
                    return None
            logger.warning(f"[captions] polling timed out after {CAPTION_BURN_MAX_WAIT_S}s")
            return None
    except Exception as exc:
        logger.warning(f"[captions] exception: {type(exc).__name__}: {exc}")
        return None
