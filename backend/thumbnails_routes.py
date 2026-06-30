"""Thumbnail Engine — text→image generation for YouTube thumbnails, Shorts
covers, and Instagram square art. Lives in its own module so server.py stays
under control as the feature surface grows.

Two providers, both routed through the Emergent Universal LLM key so users
never need to bring their own image-gen keys:

  • Premium → OpenAI gpt-image-1 (quality="hd"). Best for hero YouTube
    thumbnails — sharper typography, better composition, more expensive.
  • Fast → Gemini "Nano Banana" (gemini-3.1-flash-image-preview). Fast and
    cheap — perfect for A/B testing 4-6 variations before committing to a
    Premium hero. Snappy enough to feel real-time in the UI.

Mounted on the same /api router as the other route registrations so the
public URL surface stays `/api/thumbnails/*`. Images persist via GridFS
under the `thumbnails` bucket so we can stream them back via the existing
`/api/files/{id}` endpoint (no separate file-server needed).

Quota: separate `thumbnailsThisCycle` counter on the buyer doc. T1=20/mo,
T2=50/mo, T3+/Founder=unlimited. Premium engine is gated behind T2+ per
tier_config.thumbnail_premium_allowed.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from pydantic import BaseModel, Field


logger = logging.getLogger("thumbnails")


# Aspect → human-readable hint we append to the prompt. The image models
# don't expose an explicit aspect parameter, but they reliably honor format
# cues embedded in the prompt. Tested on both gpt-image-1 + Nano Banana.
ASPECT_HINTS: dict[str, str] = {
    "16_9": "Format: 16:9 widescreen landscape composition, optimized as a YouTube video thumbnail. Bold focal subject, high contrast, clear negative space on the upper-right or upper-left for overlay text.",
    "9_16":  "Format: 9:16 vertical portrait composition, optimized as a YouTube Shorts / Instagram Reels / TikTok cover. Subject framed in the upper-third, eye-line clear of platform UI overlays.",
    "1_1":  "Format: 1:1 square composition, optimized for Instagram feed posts. Balanced central subject, edge-safe layout (no critical detail in the outer 10%).",
}

# Viral thumbnail style suffix appended to EVERY final image prompt before
# it hits gpt-image-1 (or Gemini Nano Banana). Forces the model toward the
# bold, high-contrast, expressive-subject aesthetic that wins clicks on
# YouTube/Shorts/Reels. Without this suffix, gpt-image-1 tends to produce
# tasteful-but-flat stock-photo compositions that get scrolled past.
#
# Note: NO explicit "no text" / "no typography" instruction here — that's
# already part of the rewriter's system prompt and gpt-image-1 sometimes
# tries to over-correct by rendering watermarks if we double up on it.
VIRAL_STYLE_SUFFIX = (
    "Photorealistic, ultra-detailed, sharp focus, 4K rendering quality. "
    "Dramatic cinematic lighting with strong rim light and high contrast. "
    "Hyper-saturated bold color palette — vivid accents, deep shadows. "
    "Professional viral YouTube thumbnail aesthetic, mirroring top creator "
    "production quality. Expressive focal subject framed prominently, "
    "clear negative space for overlay text. Eye-catching at thumbnail size."
)


# Premium engine is OpenAI's flagship. Gemini's Nano Banana is the fast lane.
# Model strings are pinned per the integration playbook — only change them
# after re-confirming with integration_playbook_expert_v2.
PREMIUM_MODEL = "gpt-image-1"
FAST_MODEL = "gemini-3.1-flash-image-preview"


class ThumbnailGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=2000)
    """Final image prompt — already rewritten if the user used the helper."""

    engine: str = Field(default="premium")
    """`premium` (OpenAI gpt-image-1) or `fast` (Gemini Nano Banana)."""

    aspect: str = Field(default="16_9")
    """`16_9` | `9_16` | `1_1`. Other values default to 16:9."""

    source_script_id: Optional[str] = None
    """Optional script id this thumbnail belongs to — lets the Scripts page
    associate generated thumbs with the script that prompted them."""


class ThumbnailRewriteRequest(BaseModel):
    raw_prompt: str = Field(..., min_length=2, max_length=1000)
    """User's casual prompt — gets rewritten into a punchy, visual prompt."""

    topic: Optional[str] = Field(default=None, max_length=300)
    """Optional script topic for extra grounding context."""


def register_thumbnail_routes(
    *,
    api: APIRouter,
    db,
    current_user_dep,
    log_activity,
    emergent_llm_key: str,
    dev_bypass_email: str,
    studio_grant_emails: set,
):
    """Mount thumbnail routes on the given /api router.

    Args:
        api: FastAPI router that all /api/* endpoints attach to.
        db: motor AsyncIOMotorDatabase.
        current_user_dep: FastAPI Depends() that returns the authenticated user.
        log_activity: async fn(type, email, detail) — server.py's _log_activity.
        emergent_llm_key: the Emergent Universal LLM key (env-loaded by server.py).
        dev_bypass_email: dev owner email exempt from quota.
        studio_grant_emails: set of emails granted free studio access.
    """
    fs = AsyncIOMotorGridFSBucket(db, bucket_name="thumbnails")

    @api.post("/thumbnails/rewrite-prompt")
    async def rewrite_prompt(payload: ThumbnailRewriteRequest, user=Depends(current_user_dep)):
        """Rewrite a casual user prompt into a punchy, visual image prompt
        with strong composition + lighting cues. Powered by Claude through
        the Emergent Universal LLM key so we don't need yet another vendor."""
        if not emergent_llm_key:
            raise HTTPException(status_code=503, detail="Image rewriter not configured.")
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433

        system = (
            "You are a thumbnail-prompt rewriter for a YouTube creator tool. "
            "Your job: take the user's casual idea and rewrite it as ONE punchy "
            "image-generation prompt (90-160 words) optimized for a VIRAL "
            "YouTube/Shorts thumbnail.\n\n"
            "MUST INCLUDE in every rewrite:\n"
            "• A specific, expressive HUMAN FOCAL SUBJECT (or a single iconic object) "
            "  taking up 40-60% of the frame. If a person: describe their exact facial "
            "  expression — shocked, gasping wide-eyed, smug grin, mouth open in awe, "
            "  finger pointing in disbelief. Avoid neutral resting faces.\n"
            "• A BOLD COLOR PALETTE with at least one high-saturation accent "
            "  (electric blue, neon red, golden yellow, magenta, cyan). State the "
            "  exact palette explicitly.\n"
            "• DRAMATIC CINEMATIC LIGHTING — rim light, golden-hour glow, hard "
            "  side-light, godrays, or studio key-light with strong shadow falloff. "
            "  Name the light type.\n"
            "• A CURIOSITY GAP visual — a transformation (before/after), a comparison "
            "  (vs / arrow), a giant number, a hidden reveal, or a 'wait, what?' "
            "  composition. Pick ONE.\n"
            "• EXPLICIT NEGATIVE SPACE on one side (upper-right or upper-left) "
            "  where overlay text will sit. State which side.\n"
            "• An aspirational, premium 'top YouTube creator' production quality — "
            "  4K, sharp focus, professional thumbnail composition.\n\n"
            "MUST AVOID:\n"
            "• Words, letters, or any typography on the image itself.\n"
            "• Generic stock-photo language ('businessman standing', 'happy woman').\n"
            "• Neutral, flat, or 'tasteful' compositions — thumbnails are LOUD.\n"
            "• Multiple humans (one focal subject only, unless the comparison "
            "  composition requires exactly two).\n"
            "• Cluttered backgrounds — keep it bold and readable at 1 inch tall.\n\n"
            "Output ONLY the rewritten prompt as a single paragraph. No preamble, no "
            "quotation marks, no markdown, no labels."
        )
        topic_hint = f"\n\nScript topic (for grounding only): {payload.topic}" if payload.topic else ""
        message = (
            f"Casual idea:\n{payload.raw_prompt}{topic_hint}\n\n"
            "Rewrite as a single, vivid image prompt."
        )

        chat = LlmChat(
            api_key=emergent_llm_key,
            session_id=f"thumb-rewrite-{uuid.uuid4().hex}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")

        try:
            response = await chat.send_message(UserMessage(text=message))
        except Exception as exc:
            logger.warning("Thumbnail prompt rewrite failed: %s: %s", type(exc).__name__, exc)
            raise HTTPException(
                status_code=502,
                detail="Couldn't rewrite the prompt right now. Please try generating with your original prompt.",
            )

        rewritten = (response or "").strip()
        if not rewritten:
            raise HTTPException(status_code=502, detail="Rewriter returned an empty response.")
        # Guard against runaway essays — clip to 1800 chars (well under model limits).
        if len(rewritten) > 1800:
            rewritten = rewritten[:1800]

        return {"rewritten_prompt": rewritten}

    @api.post("/thumbnails/generate")
    async def generate_thumbnail(payload: ThumbnailGenerateRequest, user=Depends(current_user_dep)):
        """Generate one thumbnail image. Quota-gated. Returns the persisted
        URL + metadata. Image is streamed back to the user via the standard
        /api/files/{id} endpoint."""
        if not emergent_llm_key:
            raise HTTPException(status_code=503, detail="Thumbnail engine not configured.")

        engine = payload.engine.strip().lower()
        if engine not in {"premium", "fast"}:
            engine = "premium"
        aspect = payload.aspect.strip() if payload.aspect else "16_9"
        if aspect not in ASPECT_HINTS:
            aspect = "16_9"

        # Quota gate (separate from render quota). Returns the post-decrement
        # buyer doc when allowed; None when bypassed; raises 402 otherwise.
        await _thumbnail_quota_gate_or_402(
            db=db,
            email=user.email,
            engine=engine,
            log_activity=log_activity,
            dev_bypass_email=dev_bypass_email,
            studio_grant_emails=studio_grant_emails,
        )

        # Compose the prompt sent to the image model in three stacked layers:
        #   1. User prompt (what the SUBJECT is)
        #   2. Aspect hint (composition + overlay-text safe zone)
        #   3. Viral style suffix (lighting, palette, "viral YouTube" quality)
        # Stacked in this order so the subject leads, the format constraint
        # follows, and the style language anchors the model in the viral-
        # thumbnail aesthetic rather than tasteful stock-photo composition.
        composed_prompt = f"{payload.prompt}\n\n{ASPECT_HINTS[aspect]}\n\n{VIRAL_STYLE_SUFFIX}"

        thumb_id = uuid.uuid4().hex
        try:
            image_bytes = await _generate_image_bytes(
                prompt=composed_prompt,
                engine=engine,
                emergent_llm_key=emergent_llm_key,
                session_id=f"thumb-gen-{thumb_id}",
            )
        except HTTPException:
            await _refund_thumbnail_slot(
                db=db, email=user.email, dev_bypass_email=dev_bypass_email,
                studio_grant_emails=studio_grant_emails,
            )
            raise
        except Exception as exc:
            logger.warning("Thumbnail generation failed: %s: %s", type(exc).__name__, exc)
            await _refund_thumbnail_slot(
                db=db, email=user.email, dev_bypass_email=dev_bypass_email,
                studio_grant_emails=studio_grant_emails,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "We couldn't generate that thumbnail. Try simplifying the prompt "
                    "or switching engines."
                ),
            )

        # Persist to GridFS under a deterministic filename so /api/files/{id}
        # can stream it back with the right Content-Type.
        metadata = {
            "owner": user.email,
            "kind": "thumbnail",
            "engine": engine,
            "model": PREMIUM_MODEL if engine == "premium" else FAST_MODEL,
            "aspect": aspect,
            "prompt": composed_prompt,
            "original_prompt": payload.prompt,
            "source_script_id": payload.source_script_id,
            "content_type": "image/png",
            "ext": "png",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        object_id = await fs.upload_from_stream(
            f"{thumb_id}.png", image_bytes, metadata=metadata,
        )

        record = {
            "_id": str(object_id),
            "owner": user.email,
            "engine": engine,
            "aspect": aspect,
            "prompt": composed_prompt,
            "original_prompt": payload.prompt,
            "source_script_id": payload.source_script_id,
            "url": _public_url(str(object_id)),
            "size": len(image_bytes),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "deleted": False,
        }
        await db.thumbnails.insert_one(record)
        await log_activity("thumbnail_generated", user.email, {
            "engine": engine,
            "aspect": aspect,
            "source_script_id": payload.source_script_id,
        })

        # Pop _id so the JSON response doesn't choke on ObjectId; also
        # rename to the public `id` shape the frontend expects.
        out = {**record}
        out["id"] = out.pop("_id")
        return out

    @api.get("/thumbnails")
    async def list_thumbnails(user=Depends(current_user_dep)):
        """Return up to the last 60 thumbnails for the current user, newest
        first. Soft-deleted entries are excluded."""
        cursor = db.thumbnails.find({
            "owner": user.email,
            "deleted": {"$ne": True},
        }).sort([("created_at", -1)]).limit(60)
        out = []
        async for doc in cursor:
            out.append({
                "id": str(doc.get("_id")),
                "engine": doc.get("engine"),
                "aspect": doc.get("aspect"),
                "prompt": doc.get("prompt"),
                "original_prompt": doc.get("original_prompt"),
                "source_script_id": doc.get("source_script_id"),
                "url": doc.get("url"),
                "created_at": doc.get("created_at"),
            })
        return {"thumbnails": out}

    @api.delete("/thumbnails/{thumb_id}")
    async def delete_thumbnail(thumb_id: str, user=Depends(current_user_dep)):
        """Soft-delete a thumbnail. Keeps the GridFS chunks around for now;
        a future cron sweep can reclaim them if disk pressure justifies it."""
        existing = await db.thumbnails.find_one({"_id": thumb_id, "owner": user.email})
        if not existing:
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        await db.thumbnails.update_one(
            {"_id": thumb_id},
            {"$set": {
                "deleted": True,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return {"ok": True}

    @api.get("/thumbnails/file/{file_id}")
    async def stream_thumbnail_file(file_id: str):
        """Stream a thumbnail PNG from the `thumbnails` GridFS bucket. The
        uploads_routes `/api/files/{id}` streamer only knows about the
        `uploads` bucket, so thumbnails get their own dedicated streamer
        here. No auth — file IDs are UUID hex (unguessable) and lookup is
        cheap. Soft-deleted thumbnails return 404."""
        # Trim a `.png` (or any) suffix so URLs like /thumbnails/file/{id}.png
        # resolve cleanly. We always return PNG so the extension is a hint
        # for the browser, not a discriminator on the server.
        clean_id = file_id.split(".", 1)[0]
        try:
            from bson import ObjectId
            oid = ObjectId(clean_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Bad file id")

        files = db["thumbnails.files"]
        doc = await files.find_one({"_id": oid})
        if not doc:
            raise HTTPException(status_code=404, detail="Thumbnail not found")

        # Cross-check the high-level `thumbnails` collection for the soft-
        # delete flag (the GridFS files metadata is a separate doc).
        record = await db.thumbnails.find_one({"_id": clean_id})
        if record and record.get("deleted"):
            raise HTTPException(status_code=404, detail="Thumbnail not found")

        async def _stream():
            stream = await fs.open_download_stream(oid)
            try:
                while True:
                    chunk = await stream.readchunk()
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    maybe_coro = stream.close()
                    if maybe_coro is not None:
                        await maybe_coro
                except Exception:
                    pass

        content_type = (doc.get("metadata") or {}).get("content_type") or "image/png"
        return StreamingResponse(
            _stream(),
            media_type=content_type,
            headers={
                "Content-Length": str(doc.get("length", 0)),
                "Cache-Control": "public, max-age=86400",
            },
        )


# ---------------------------------------------------------------------------
# Image provider plumbing — converts a single prompt into PNG bytes.
# ---------------------------------------------------------------------------

async def _generate_image_bytes(
    *,
    prompt: str,
    engine: str,
    emergent_llm_key: str,
    session_id: str,
) -> bytes:
    """Dispatch to the right provider and return raw PNG bytes."""
    if engine == "fast":
        return await _gen_via_gemini(
            prompt=prompt, emergent_llm_key=emergent_llm_key, session_id=session_id,
        )
    return await _gen_via_openai(prompt=prompt, emergent_llm_key=emergent_llm_key)


async def _gen_via_openai(*, prompt: str, emergent_llm_key: str) -> bytes:
    """Premium → OpenAI gpt-image-1 at HD quality."""
    from emergentintegrations.llm.openai.image_generation import OpenAIImageGeneration  # noqa: WPS433

    image_gen = OpenAIImageGeneration(api_key=emergent_llm_key)
    try:
        images = await asyncio.wait_for(
            image_gen.generate_images(
                prompt=prompt,
                model=PREMIUM_MODEL,
                number_of_images=1,
                quality="hd",
            ),
            timeout=90.0,  # 60s is the model's typical max; pad for network.
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Premium engine timed out. Try Fast instead.")

    if not images:
        raise HTTPException(status_code=502, detail="OpenAI returned no image.")
    return images[0]


async def _gen_via_gemini(*, prompt: str, emergent_llm_key: str, session_id: str) -> bytes:
    """Fast → Gemini Nano Banana via LlmChat multimodal response."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433

    chat = (
        LlmChat(
            api_key=emergent_llm_key,
            session_id=session_id,
            system_message="You are an image generator. Produce a single image matching the user's prompt.",
        )
        .with_model("gemini", FAST_MODEL)
        .with_params(modalities=["image", "text"])
    )
    try:
        _, images = await asyncio.wait_for(
            chat.send_message_multimodal_response(UserMessage(text=prompt)),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Fast engine timed out. Please retry.")

    if not images:
        raise HTTPException(status_code=502, detail="Gemini returned no image.")
    # Gemini returns [{mime_type, data: base64}, ...]
    return base64.b64decode(images[0]["data"])


# ---------------------------------------------------------------------------
# Quota gate — mirrors the render-quota pattern in server.py but counts
# `thumbnailsThisCycle` instead of `rendersThisCycle`.
# ---------------------------------------------------------------------------

async def _thumbnail_quota_gate_or_402(
    *,
    db,
    email: str,
    engine: str,
    log_activity,
    dev_bypass_email: str,
    studio_grant_emails: set,
) -> Optional[dict]:
    """Atomic per-thumbnail check + decrement. Raises HTTPException(402)
    with a frontend-friendly body on exhaustion or premium-locked tier.
    Returns None for founders/dev/grant (no refund needed)."""
    if dev_bypass_email and email == dev_bypass_email:
        return None
    if email in studio_grant_emails:
        return None

    buyer = await db.buyers.find_one({"email": email})
    if not buyer:
        raise HTTPException(status_code=403, detail="Buyer record missing")
    if buyer.get("founders"):
        return None

    from tier_config import get_tier, tier_for_entitlements  # noqa: WPS433
    tier_id = (buyer.get("tier") or "").strip().lower()
    if not tier_id:
        tier_id = tier_for_entitlements(list(buyer.get("entitlements") or [])).id
    tier = get_tier(tier_id)

    used = int(buyer.get("thumbnailsThisCycle") or 0)
    quota = int(buyer.get("thumbnailQuotaMonthly") or tier.thumbnail_quota_monthly)
    cycle_ends = buyer.get("cycleResetsAt")
    premium_allowed = bool(
        buyer.get("thumbnailPremiumAllowed")
        if buyer.get("thumbnailPremiumAllowed") is not None
        else tier.thumbnail_premium_allowed
    )

    # Gate 1 — Premium locked behind T2+ per tier_config. The Fast engine
    # remains available so the user still has a path forward.
    if engine == "premium" and not premium_allowed:
        await log_activity("quota_blocked", email, {
            "reason": "thumbnail_premium_locked", "tier": tier_id,
        })
        raise HTTPException(
            status_code=402,
            detail={
                "reason": "thumbnail_premium_locked",
                "message": (
                    "Premium thumbnails are part of the Scripts + Shorts tier and up. "
                    "Switch to Fast to keep generating, or upgrade to unlock Premium."
                ),
                "tier": tier_id,
            },
        )

    if quota <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "reason": "thumbnail_quota_zero",
                "message": "Your tier doesn't include thumbnail generation yet. Upgrade to unlock.",
                "tier": tier_id,
            },
        )

    # Build days-left + upgrade-to copy, same shape as render gate so the
    # frontend's friendlyRenderError handler renders consistently.
    days_left = ""
    if cycle_ends:
        try:
            resets_at = datetime.fromisoformat(cycle_ends.replace("Z", "+00:00"))
            d = max(0, (resets_at - datetime.now(timezone.utc)).days)
            days_left = (
                f" Resets in {d} day{'s' if d != 1 else ''}."
                if d > 0 else " Resets within the next hour."
            )
        except Exception:
            pass

    if used >= quota:
        await log_activity("quota_blocked", email, {
            "reason": "thumbnail_quota_exhausted",
            "tier": tier_id, "used": used, "total": quota,
        })
        raise HTTPException(
            status_code=402,
            detail={
                "reason": "thumbnail_quota_exhausted",
                "message": f"You've used all {quota} thumbnails this cycle.{days_left}",
                "quota_used": used,
                "quota_total": quota,
                "cycle_resets_at": cycle_ends,
                "tier": tier_id,
            },
        )

    # Atomic decrement — same race-safe pattern as the render gate.
    updated = await db.buyers.find_one_and_update(
        {
            "email": email,
            "$expr": {"$lt": [{"$ifNull": ["$thumbnailsThisCycle", 0]}, quota]},
        },
        {"$inc": {"thumbnailsThisCycle": 1}},
        return_document=True,
    )
    if not updated:
        await log_activity("quota_blocked", email, {
            "reason": "thumbnail_race_lost", "tier": tier_id,
        })
        raise HTTPException(
            status_code=402,
            detail={
                "reason": "thumbnail_quota_exhausted",
                "message": f"You've used all {quota} thumbnails this cycle.{days_left}",
                "quota_used": used,
                "quota_total": quota,
                "tier": tier_id,
            },
        )
    return updated


async def _refund_thumbnail_slot(
    *,
    db,
    email: str,
    dev_bypass_email: str,
    studio_grant_emails: set,
) -> None:
    """Reverse a thumbnail-quota decrement when generation fails after the
    gate accepted it. Safe to call multiple times (the `founders` guard +
    the upsert=False semantics keep it idempotent)."""
    if dev_bypass_email and email == dev_bypass_email:
        return
    if email in studio_grant_emails:
        return
    try:
        await db.buyers.update_one(
            {"email": email, "founders": {"$ne": True}},
            {"$inc": {"thumbnailsThisCycle": -1}},
        )
    except Exception as exc:
        logger.warning("[thumb] refund failed for %s: %s: %s", email, type(exc).__name__, exc)


def _public_url(file_id: str) -> str:
    """Build a public URL the frontend can fetch the thumbnail from. We
    route to the dedicated `/api/thumbnails/file/{id}` streamer (defined
    above) so the `thumbnails` GridFS bucket stays cleanly isolated from
    the `uploads` bucket. The `.png` suffix is a hint to the browser only."""
    base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    if base:
        return f"{base}/api/thumbnails/file/{file_id}.png"
    return f"/api/thumbnails/file/{file_id}.png"
