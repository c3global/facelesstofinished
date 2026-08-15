"""Pure scene-routing helpers for Faceless Studio B-roll.

Customer uploads are source material, never prompts for an AI provider.  Keep
that distinction in one small module so it can be tested without importing the
FastAPI application or requiring provider credentials.
"""

from __future__ import annotations

from urllib.parse import urlparse


_IMAGE_EXTENSIONS = {".avif", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".webp"}
_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm"}


def uploaded_media_kind(scene: dict) -> str:
    """Return ``image`` or ``video`` for a customer-uploaded B-roll item.

    New clients send an explicit ``kind``.  Extension sniffing keeps uploads
    made by older clients working.  Unknown legacy URLs retain the historical
    video treatment because that is safer than accidentally treating a video
    as a still image.
    """

    explicit = str(scene.get("kind") or scene.get("media_kind") or "").strip().lower()
    if explicit in {"image", "video"}:
        return explicit

    media_url = str(scene.get("video_url") or scene.get("url") or "")
    path = urlparse(media_url).path.lower()
    dot = path.rfind(".")
    extension = path[dot:] if dot >= 0 else ""
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _VIDEO_EXTENSIONS:
        return "video"
    return "video"


def classify_scene_kind(scene: dict, global_source: str, is_t2v: bool) -> str:
    """Classify a scene without making any network or provider decisions."""

    source = str(scene.get("source") or global_source or "").strip().lower()
    if source == "uploaded":
        return f"uploaded_{uploaded_media_kind(scene)}"
    if source == "ai":
        return "ai_t2v" if is_t2v else "ai"
    return "stock"


def count_visual_scene_sources(
    scenes: list[dict], global_source: str, inferred_scene_count: int,
) -> tuple[int, int, int]:
    """Return AI, stock, and uploaded counts for provider-cost estimation."""

    if not scenes:
        source = str(global_source or "pexels").strip().lower()
        count = max(1, inferred_scene_count)
        if source == "ai":
            return count, 0, 0
        if source == "uploaded":
            return 0, 0, count
        return 0, count, 0

    ai_count = stock_count = uploaded_count = 0
    for scene in scenes:
        source = str(scene.get("source") or global_source or "pexels").strip().lower()
        if source == "ai":
            ai_count += 1
        elif source == "uploaded":
            uploaded_count += 1
        else:
            stock_count += 1
    return ai_count, stock_count, uploaded_count


def cutaway_subclip_slot(scene_idx: int, cut_idx: int) -> int:
    """Return a temp-file slot that cannot collide with a final scene slot.

    Final scene files use their zero-based scene index (currently capped at
    200).  A high reserved namespace keeps parallel cutaway files distinct
    from every final ``scene_NNN.mp4`` path.
    """

    return 1_000_000 + (scene_idx * 100) + cut_idx


def is_local_media_reference(value: object) -> bool:
    """Whether a compose reference denotes a local filesystem path."""

    return isinstance(value, str) and value.startswith("/")
