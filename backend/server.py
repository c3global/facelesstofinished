"""F2F48 Studio backend — FastAPI.

Auth model: Netlify (faceless48.c3global.co) is the source of truth for paying
customers + entitlements. This backend either (a) forwards the user's cookies
to the Netlify /api/auth-me endpoint and trusts its response, or (b) honors a
DEV_BYPASS_EMAIL env var so the Studio UI is testable on the Emergent preview
URL where cross-domain cookies aren't available.

After a successful Netlify auth-me handshake we mint a short-lived JWT and
store it in MongoDB so subsequent calls don't re-hit Netlify on every request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
import wave
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import fal_client
import httpx
import imageio_ffmpeg
import jwt
from dotenv import load_dotenv
from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from prompts import (
    build_long_system_prompt,
    build_shorts_system_prompt,
    build_sprint_system_prompt,
    BROLL_PROMPTS_SYSTEM,
    ANGLES_SYSTEM_PROMPT,
    build_angles_user_message,
)
# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# IMPORTANT: load_dotenv() MUST run before importing admin_routes, because
# admin_routes reads PINBALL_WEBHOOK_TOKEN at module-import time.
load_dotenv()

from admin_routes import register_admin_routes  # noqa: E402
from uploads_routes import register_uploads_routes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("f48")
logger.setLevel(logging.INFO)

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
HEYGEN_API_KEY = os.environ.get("HEYGEN_API_KEY", "")
FAL_API_KEY = os.environ.get("FAL_API_KEY", "")

# BYOK runtime overrides — set at the top of each render path when the
# buyer has saved a customer API key. Helpers read via the
# `_effective_*_key()` accessors so platform defaults stay in place for
# everything outside the active render coroutine (avatar listings, TTS
# preloads, storage uploads, etc).
import contextvars  # noqa: E402  – kept beside the env reads for grouping
_override_heygen_key_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("override_heygen_key", default=None)
_override_fal_key_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("override_fal_key", default=None)


def _effective_heygen_key() -> str:
    return _override_heygen_key_ctx.get() or HEYGEN_API_KEY


def _effective_fal_key() -> str:
    return _override_fal_key_ctx.get() or FAL_API_KEY
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
DEV_BYPASS_EMAIL = os.environ.get("DEV_BYPASS_EMAIL", "").strip().lower()
# Manual studio grants — comma-separated list of email addresses that get
# instant studio access without hitting Netlify. Used to hand-onboard founders
# during the brief window before the Pinball → GHL → Netlify webhook chain is
# fully wired in production. Also serves as a permanent admin backstop so the
# owner can't be locked out by a Netlify outage.
STUDIO_GRANT_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("STUDIO_GRANT_EMAILS", "").split(",")
    if e.strip()
}
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "drcharitycampbell@gmail.com").split(",")
    if e.strip()
}
# Silent runaway-cost circuit-breaker. NOT customer-facing — exists to catch
# pathological inputs (malformed scripts, scene counts, etc.) before they hit
# a paid API. When this fires, customers see a generic "Render configuration
# is too large. Please contact support." Log loudly so we can investigate &
# raise the threshold.
RENDER_COST_CIRCUIT_BREAKER_CENTS = int(os.environ.get("RENDER_COST_CAP_CENTS", "500"))

KNOWN_ENTITLEMENTS = ["base", "shorts", "studio"]
JWT_ALG = "HS256"
JWT_TTL_HOURS = 24

mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo[DB_NAME]

app = FastAPI(title="F2F48 Studio API", version="0.1.0")
# CORS — v1.15.0 — switched from `allow_origins=["*"] + allow_credentials=True`
# (which is invalid per the W3C CORS spec — browsers silently reject the
# combination on cross-origin /auth/me calls from the deployed frontend)
# to either:
#   - an explicit whitelist via FRONTEND_ORIGINS env var, OR
#   - a regex wildcard when no whitelist is set (still safe because our
#     auth boundary is the bearer JWT, not the origin).
# `allow_credentials=False` because the frontend ships JWT in the
# Authorization header, not in cookies. This fixes the previously-broken
# cross-origin /api/auth/me + /api/me/quota path when frontend is served
# from a different host than the backend (e.g. on the production domain
# vs the kubernetes preview URL).
_frontend_origins = (os.environ.get("FRONTEND_ORIGINS") or "").strip()
if _frontend_origins:
    _origins_list = [o.strip() for o in _frontend_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

api = FastAPI()  # mounted at /api below


# ---------------------------------------------------------------------------
# Startup hooks — non-blocking pre-warm tasks.
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _prewarm_heygen_caches() -> None:
    """Kick off a background task that warms the HeyGen avatar + voice
    caches so the first user after a redeploy doesn't wait 60+ seconds
    for HeyGen's slow /v2/avatars endpoint. Non-blocking: startup returns
    immediately, the cache fills asynchronously in the background.

    Skips if HEYGEN_API_KEY isn't set (preview without integration) or if
    the cache is already fresh (TTL 24h). Failures are logged but do not
    bring down the app — picker endpoints will just refill on demand.
    """
    import asyncio  # noqa: PLC0415 — local import keeps startup latency low

    async def _warm() -> None:
        if not os.environ.get("HEYGEN_API_KEY"):
            logger.info("[prewarm] HEYGEN_API_KEY not set; skipping cache warm")
            return
        for key, fetch in (
            ("heygen_avatars_v2", _fetch_heygen_avatars),
            ("heygen_voices_v3", _fetch_heygen_voices),
        ):
            try:
                # _cached already short-circuits when the entry is fresh.
                started = datetime.now(timezone.utc)
                data = await _cached(key, 24, fetch)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                logger.info(f"[prewarm] {key}: {len(data) if isinstance(data, list) else '?'} items in {elapsed:.1f}s")
            except Exception as exc:  # noqa: BLE001 — never crash startup
                logger.warning(f"[prewarm] {key} failed: {type(exc).__name__}: {exc}")

    # Detach so startup returns immediately. The container is "ready" the
    # moment the API can serve /health; the cache fills in the background.
    asyncio.create_task(_warm())


# ---------------------------------------------------------------------------
# Cycle reset loop — Group B of the AppSumo launch plan.
#
# Every hour, scan buyers whose anniversary cycle is due and roll their
# counters forward. Founders bypass entirely (no quota → no cycle). Wrapped
# in try/except so a transient Mongo error never crashes the loop.
#
# Uses asyncio.sleep + asyncio.create_task instead of apscheduler so the
# codebase stays dependency-free. The 1-hour interval is fine for monthly
# cycles — a buyer whose cycle was due at 03:17 just gets reset at the next
# hourly tick by 04:00 worst-case. Under 1-hour drift on a 30-day cycle.
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _start_cycle_reset_loop() -> None:
    from tier_config import fresh_cycle_payload  # local import — avoids cycle risk

    async def _reset_due_cycles() -> int:
        """Advance every buyer whose cycleResetsAt has passed. Returns the
        number of buyers reset (used for log volume management — only log on
        non-zero days)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        query = {
            "cycleResetsAt": {"$lte": now_iso},
            "$or": [{"founders": {"$ne": True}}, {"founders": {"$exists": False}}],
        }
        # Snapshot count + iterate so we can log who was reset (Activity row
        # per reset for the admin Activity tab — keeps reset history auditable).
        emails: list[str] = []
        async for b in db.buyers.find(query, {"email": 1}):
            emails.append(b["email"])
        if not emails:
            return 0
        payload = fresh_cycle_payload()
        await db.buyers.update_many(
            {"email": {"$in": emails}},
            {"$set": payload},
        )
        # Compact single activity row covering this batch — beats N rows on
        # the 1st of each month when ~all buyers reset at once.
        try:
            await db.activity.insert_one({
                "id": str(uuid.uuid4()),
                "ts": now_iso,
                "type": "cycle_reset_batch",
                "email": "system",
                "detail": {"count": len(emails), "emails": emails[:20], "truncated": len(emails) > 20},
            })
        except Exception:
            pass  # telemetry only — never block the reset itself
        return len(emails)

    async def _loop() -> None:
        # Wait 30s after startup so the warm-up tasks complete first before
        # we start hitting Mongo with the cycle scan. Subsequent ticks run
        # every hour.
        await asyncio.sleep(30)
        while True:
            try:
                n = await _reset_due_cycles()
                if n:
                    logger.info(f"[cycle-reset] advanced {n} buyer(s)")
            except Exception as exc:  # noqa: BLE001 — keep loop alive forever
                logger.warning(f"[cycle-reset] tick failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(3600)  # 1 hour

    import asyncio  # noqa: PLC0415
    asyncio.create_task(_loop())




# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AuthUser(BaseModel):
    email: str
    entitlements: list[str] = []
    # `isAdmin` is sourced from Netlify auth-me when the cross-origin handshake
    # is used; falls back to the local ADMIN_EMAILS env var. We carry it in
    # the JWT (rather than re-deriving on every request) so future changes to
    # the source list don't accidentally lock active sessions out of admin UI.
    is_admin: bool = False


class LoginPayload(BaseModel):
    email: str
    # Vestigial — was used for the Netlify cross-origin handshake which is
    # now retired. Frontend still sends `cookies: ""` so we accept the
    # field as a no-op for backward compatibility. Safe to drop in a
    # future frontend cleanup pass.
    cookies: Optional[str] = None


class RenderRequest(BaseModel):
    mode: str  # "avatar" | "faceless" | "composite"
    script: str
    aspect: str = "9_16"  # "9_16" | "16_9"
    # Captions are OFF by default to avoid surprise charges for API-only
    # callers (the UI always sends an explicit value via the CaptionsPicker).
    # Enabling triggers a second-pass fal.ai/auto-subtitle burn-in at +$0.10.
    captions: bool = False
    caption_style: str = "boxed"           # boxed | tiktok | minimal
    # Vertical placement override — applies to all three styles. UI default
    # is "bottom" which matches every style preset's default.
    caption_position: str = "bottom"       # top | bottom | center
    # Avatar mode
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None
    # Faceless mode
    tts_voice_id: Optional[str] = None
    # If set, the user uploaded their own recorded voiceover via the
    # /api/studio/uploads/voiceover endpoint. The render pipeline skips
    # Kokoro entirely and uses this URL as the audio track. Scene durations
    # are still computed from the actual audio length (via ffprobe).
    user_voiceover_url: Optional[str] = None
    broll_source: Optional[str] = None  # "ai" | "pexels" | "pixabay" | "mix" | "uploaded"
    scenes: list[dict] = Field(default_factory=list)
    # AI video engine for AI-sourced scenes (Faceless mode):
    #   - "flux" → Flux 1.1 Pro static image + ken-burns motion (fast, cheap)
    #   - "kling" → Kling 2.1 Master text-to-video (premium, cinematic)
    #   - "veo3" → Google Veo 3.1 Fast text-to-video (Google quality)
    #   - "pika" → Pika 2.1 text-to-video (cheaper t2v option)
    # Stock scenes (Pexels/Pixabay) ignore this field. Default keeps existing
    # behaviour for users who never touched the picker.
    ai_engine: str = "flux"
    # Composite mode — interleave avatar talking-head with B-roll cutaways
    broll_cutaway_interval_s: int = 12
    # Caption styling preset (faceless mode only — HeyGen handles its own
    # styling automatically for Avatar). One of: "minimal" (white text only),
    # "boxed" (white text on translucent black box), "bold-yellow" (TikTok
    # style — bold yellow w/ shadow), "outlined" (white text w/ thick black
    # outline). Stored on the doc; consumed by the optional caption-burn-in
    # step at the end of the faceless pipeline.
    caption_style: str = "boxed"
    caption_position: str = "bottom"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def issue_jwt(email: str, entitlements: list[str], is_admin: bool = False) -> str:
    payload = {
        "email": email,
        "entitlements": entitlements,
        "isAdmin": is_admin,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_TTL_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


async def current_user(authorization: Optional[str] = Header(default=None)) -> AuthUser:
    """Require a valid bearer JWT. Used to gate Studio endpoints."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing auth")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return AuthUser(
        email=payload["email"],
        entitlements=payload.get("entitlements", []),
        is_admin=bool(payload.get("isAdmin")) or payload["email"].lower() in ADMIN_EMAILS,
    )


def require_studio(user: AuthUser) -> None:
    if "studio" not in user.entitlements:
        raise HTTPException(status_code=403, detail="Studio entitlement required")


async def require_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    """Top-level admin dependency. `admin_routes.py` defines its own inner
    copy for historical reasons; this one is shared with `licenses_routes.py`
    and any future modular routers that need the same gate."""
    if not (user.is_admin or user.email.lower() in ADMIN_EMAILS):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@api.get("/health")
async def health():
    return {"ok": True}


@api.post("/auth/check")
async def auth_check(payload: LoginPayload):
    """Verify a user has Studio access.

    Resolution order (first match wins):
      1. `DEV_BYPASS_EMAIL` — preview/local-only single-email bypass so devs
         can hit the Studio UI without touching production data. Set ONLY in
         the preview .env; never in production env vars.
      2. `STUDIO_GRANT_EMAILS` — comma-separated list of hand-onboarded
         founders that get instant access. Permanent admin backstop.
      3. `db.buyers` lookup — admin-added buyers (Admin → Buyers UI) and
         Pinball-webhook buyers (auto-populated on paid orders). LIVE
         source of truth for paying customers since the Netlify→Emergent
         migration. Returns a one-time `welcome` field on first sign-in
         after a Pinball auto-grant so the UI can celebrate.
    """
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    # Stamp a real "last seen" timestamp on the buyer record AFTER a successful
    # sign-in. The pre-fix admin Stats tab was reading lastLoginAt from CSV
    # imports + webhook payloads only — meaning users who actually signed in
    # via this endpoint never got a real timestamp, and the "Active users
    # (30d)" metric was effectively stale historical data. We update inside
    # each successful resolution path below (not here at the top) so failed
    # auth attempts don't pollute the timestamp, and we use `update_one` with
    # `upsert=False` so DEV_BYPASS / STUDIO_GRANT users without a buyer
    # record don't accidentally create one. Idempotent + cheap (one indexed
    # email lookup + one $set per successful sign-in).
    async def _stamp_last_login() -> None:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.buyers.update_one(
                {"email": email},
                {
                    "$set": {"lastLoginAt": now_iso, "updatedAt": now_iso},
                    "$inc": {"loginCount": 1},
                },
                upsert=False,
            )
        except Exception:
            # Never block sign-in on a telemetry write — log silently and
            # let the auth flow continue. Worst case: the user signs in,
            # stat doesn't tick. Better than a 500 on a successful login.
            pass

    # 1) Dev bypass — preview env only.
    if DEV_BYPASS_EMAIL and email == DEV_BYPASS_EMAIL:
        is_admin = email in ADMIN_EMAILS
        token = issue_jwt(email, KNOWN_ENTITLEMENTS, is_admin=is_admin)
        await _stamp_last_login()
        return {
            "token": token,
            "user": {"email": email, "entitlements": KNOWN_ENTITLEMENTS, "isAdmin": is_admin},
        }

    # 2) Manual grant — admin backstop + founder onboarding window.
    if email in STUDIO_GRANT_EMAILS:
        is_admin = email in ADMIN_EMAILS
        token = issue_jwt(email, KNOWN_ENTITLEMENTS, is_admin=is_admin)
        await _stamp_last_login()
        return {
            "token": token,
            "user": {"email": email, "entitlements": KNOWN_ENTITLEMENTS, "isAdmin": is_admin},
        }

    # 3) Database-backed buyer lookup — admin-added buyers + Pinball-webhook
    #    buyers. This is the SOURCE OF TRUTH for paying customers since the
    #    Netlify→Emergent migration. The admin Buyers UI writes here, and the
    #    Pinball webhook auto-populates this collection on every paid order.
    buyer = await db.buyers.find_one({"email": email})
    if buyer:
        ents = list(buyer.get("entitlements") or [])
        is_admin = email in ADMIN_EMAILS
        # Admins can sign in even with no entitlements (so an owner without
        # a purchase record can still use the app). Everyone else needs at
        # least one entitlement on file. Empty-entitlement buyers are
        # treated as "revoked" — admin can re-grant via the Buyers UI.
        if is_admin and not ents:
            ents = list(KNOWN_ENTITLEMENTS)
        if ents:
            # First-sign-in welcome flag — set by the Pinball webhook when it
            # auto-provisions a buyer. We read it ONCE on first sign-in and
            # clear it atomically so the frontend can show a "Welcome — access
            # granted" toast exactly once per Pinball grant.
            welcome = None
            if buyer.get("pending_welcome"):
                welcome = {
                    "entitlements": list(buyer.get("pending_welcome_ents") or ents),
                    "source": "pinball",
                }
                await db.buyers.update_one(
                    {"email": email},
                    {"$unset": {"pending_welcome": "", "pending_welcome_ents": ""}},
                )
            token = issue_jwt(email, ents, is_admin=is_admin)
            await _stamp_last_login()
            response = {
                "token": token,
                "user": {"email": email, "entitlements": ents, "isAdmin": is_admin},
            }
            if welcome:
                response["welcome"] = welcome
            return response

    # 4) No remaining resolution path. The cross-origin Netlify auth-me
    #    handshake was retired with the Netlify site itself — db.buyers is
    #    now the single source of truth. Anyone who can't sign in here
    #    either hasn't been admin-granted or hasn't completed a Pinball
    #    purchase (or used a different email at checkout).
    raise HTTPException(status_code=401, detail="Could not sign in. Use the email you bought with.")


@api.get("/auth/me")
async def auth_me(user: AuthUser = Depends(current_user)):
    return {
        "email": user.email,
        "entitlements": user.entitlements,
        "isAdmin": user.is_admin,
    }


# ---------------------------------------------------------------------------
# Quota status — drives the Studio header pill ("12 of 15 renders · resets…")
# ---------------------------------------------------------------------------
# Returns a customer-facing snapshot of the buyer's current cycle: their tier
# label, how many renders they've used vs their cap, the avatar sub-cap, when
# the cycle resets, and a boolean `unlimited` flag for founders / dev / grant
# emails so the UI can hide the pill entirely (no caps to display).
#
# Internal-only fields (cost cents, kill-switch ceiling) are NOT exposed —
# the cost cap is a SILENT backstop per the AppSumo launch spec.
# ---------------------------------------------------------------------------
@api.get("/me/quota")
async def me_quota(user: AuthUser = Depends(current_user)):
    from tier_config import get_tier, tier_for_entitlements

    # Dev bypass / studio-grant emails are treated as unlimited in the pill.
    if (DEV_BYPASS_EMAIL and user.email == DEV_BYPASS_EMAIL) or user.email in STUDIO_GRANT_EMAILS:
        return {
            "unlimited": True,
            "tier_id": "owner",
            "tier_label": "Owner",
            "byok_allowed": True,
        }

    buyer = await db.buyers.find_one({"email": user.email}) or {}
    if buyer.get("founders"):
        return {
            "unlimited": True,
            "tier_id": "founder",
            "tier_label": "Founder",
            "byok_allowed": True,
        }

    tier_id = (buyer.get("tier") or "").strip().lower()
    if not tier_id:
        tier_id = tier_for_entitlements(list(buyer.get("entitlements") or [])).id
    tier = get_tier(tier_id)

    used_total  = int(buyer.get("rendersThisCycle") or 0)
    used_avatar = int(buyer.get("avatarRendersThisCycle") or 0)
    used_thumbs = int(buyer.get("thumbnailsThisCycle") or 0)
    quota_total = int(buyer.get("renderQuotaMonthly") or tier.render_quota_monthly)
    avatar_cap  = int(buyer.get("avatarSubCap") or tier.avatar_sub_cap)
    thumb_quota = int(buyer.get("thumbnailQuotaMonthly") or tier.thumbnail_quota_monthly)
    premium_ok  = bool(
        buyer.get("thumbnailPremiumAllowed")
        if buyer.get("thumbnailPremiumAllowed") is not None
        else tier.thumbnail_premium_allowed
    )

    return {
        "unlimited": False,
        "tier_id": tier.id,
        "tier_label": tier.label,
        "renders_used": used_total,
        "renders_total": quota_total,
        "renders_remaining": max(0, quota_total - used_total),
        "avatar_used": used_avatar,
        "avatar_cap": avatar_cap,
        "avatar_remaining": max(0, avatar_cap - used_avatar) if avatar_cap > 0 else 0,
        "thumbnails_used": used_thumbs,
        "thumbnails_total": thumb_quota,
        "thumbnails_remaining": max(0, thumb_quota - used_thumbs),
        "thumbnail_premium_allowed": premium_ok,
        "cycle_started_at": buyer.get("cycleStartedAt"),
        "cycle_resets_at": buyer.get("cycleResetsAt"),
        "byok_allowed": bool(buyer.get("byokAllowed") if buyer.get("byokAllowed") is not None else tier.byok_allowed),
    }


# ---------------------------------------------------------------------------
# Lightweight activity logger — frontend pings this for soft engagement
# events (script copied, script sent to Studio, video played, history opened)
# so the Stats / Usage admin tabs can show real per-customer behavior.
#
# Strict allow-list on the type field so a leaky frontend can't pollute the
# activity collection. Quietly drops unknown types (returns ok=False) rather
# than 4xx-ing the UI.
# ---------------------------------------------------------------------------
_USER_ACTIVITY_TYPES = {
    "script_copied",
    "script_sent_to_studio",
    "video_played",
    "script_opened_from_history",
}


class UserActivityRequest(BaseModel):
    type: str
    detail: Optional[dict] = None


@api.post("/activity/log")
async def post_activity_log(payload: UserActivityRequest, user: AuthUser = Depends(current_user)):
    if payload.type not in _USER_ACTIVITY_TYPES:
        return {"ok": False, "reason": "type not allowed"}
    detail = payload.detail or {}
    # Trim payload to keep activity rows small. We mostly care about presence
    # + frequency for engagement metrics, not deep context.
    if isinstance(detail, dict):
        detail = {k: detail[k] for k in list(detail.keys())[:8]}
    await _log_activity(payload.type, user.email, detail)
    return {"ok": True}


# ---------------------------------------------------------------------------
# HeyGen — avatars + voices (with 24h Mongo cache)
# ---------------------------------------------------------------------------
async def _heygen_get(path: str) -> dict:
    if not HEYGEN_API_KEY:
        raise HTTPException(status_code=500, detail="HeyGen key missing")
    # HeyGen v2 /avatars can take ~60s for the full 1281-avatar response on a
    # cache miss. Voices upstream is fast (<10s). Use 90s read timeout to cover
    # both; cached for 24h afterwards so this hit only happens once per day.
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
        r = await client.get(
            f"https://api.heygen.com/v2{path}",
            headers={"X-Api-Key": HEYGEN_API_KEY, "Accept": "application/json"},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"HeyGen error {r.status_code}")
    return r.json()


async def _cached(key: str, ttl_hours: int, fetch):
    doc = await db.cache.find_one({"_id": key})
    now = datetime.now(timezone.utc)
    if doc and doc.get("expires_at"):
        exp = doc["expires_at"]
        # Mongo returns tz-naive datetimes (stored as UTC); make aware to compare
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now:
            return doc["data"]
    data = await fetch()
    await db.cache.update_one(
        {"_id": key},
        {"$set": {"data": data, "expires_at": now + timedelta(hours=ttl_hours)}},
        upsert=True,
    )
    return data


async def _fetch_heygen_avatars() -> list[dict]:
    """Fetch + normalize HeyGen avatars. Module-level so the startup
    pre-warm task can call this without an authenticated request."""
    raw = await _heygen_get("/avatars")
    avatars = (raw.get("data") or {}).get("avatars") or []
    out = []
    for a in avatars:
        name = (a.get("avatar_name") or "").lower()
        # Heuristic aspect tagging based on the pose hint in the name.
        # HeyGen v2 `aspect_ratio: "9:16"` only sets the output canvas —
        # it does NOT crop or zoom a 16:9 source. So sitting / side /
        # full-body poses get rendered into a portrait canvas with
        # huge top/bottom padding. The picker MUST filter these out.
        # Landscape keywords VETO portrait keywords (a "sofa front" is
        # still a sitting shot, regardless of the "front" word).
        landscape_only = any(t in name for t in (
            " side", "sofa", "biztalk", "wide", "couch", "background",
            "office", "sitting", "desk", "studio",
        ))
        portrait_ok = any(t in name for t in (
            "upper body", "headshot", "close", "selfie", "portrait",
        ))
        if landscape_only:
            aspect = "landscape"
        elif portrait_ok:
            aspect = "portrait"
        else:
            aspect = "both"
        out.append({
            "id": a.get("avatar_id"),
            "name": a.get("avatar_name") or a.get("avatar_id"),
            "preview_image_url": a.get("preview_image_url"),
            "preview_video_url": a.get("preview_video_url"),
            "gender": (a.get("gender") or "").lower() or "other",
            "premium": bool(a.get("premium")),
            "aspect": aspect,
        })
    return out


async def _fetch_heygen_voices() -> list[dict]:
    """Fetch + normalize HeyGen voices. Module-level for the startup
    pre-warm task. Filters out custom voice clones (preview_audio=null
    + support_locale=false) so users only see the global library."""
    raw = await _heygen_get("/voices")
    voices = (raw.get("data") or {}).get("voices") or []
    out = []
    for v in voices:
        if not v.get("preview_audio") and not v.get("support_locale"):
            continue
        g = (v.get("gender") or "").lower()
        if g not in ("female", "male"):
            g = "other"
        out.append({
            "id": v.get("voice_id"),
            "name": v.get("name") or v.get("voice_id"),
            "gender": g,
            "language": v.get("language") or "",
            "preview_audio": v.get("preview_audio"),
        })
    return out


@api.get("/studio/avatars")
async def studio_avatars(user: AuthUser = Depends(current_user)):
    require_studio(user)
    avatars = await _cached("heygen_avatars_v2", 24, _fetch_heygen_avatars)
    return {"avatars": avatars}


@api.get("/studio/voices")
async def studio_voices(user: AuthUser = Depends(current_user)):
    require_studio(user)
    voices = await _cached("heygen_voices_v3", 24, _fetch_heygen_voices)
    return {"voices": voices}


# ---------------------------------------------------------------------------
# Voice favorites — pinned voices per user, stored in db.buyers.favorite_voices.
# Reused across all voice pickers (HeyGen avatar voices today; could extend to
# Kokoro TTS later).
# ---------------------------------------------------------------------------
class FavoriteVoiceRequest(BaseModel):
    voice_id: str


@api.get("/studio/voices/favorites")
async def studio_voices_favorites(user: AuthUser = Depends(current_user)):
    require_studio(user)
    doc = await db.buyers.find_one({"email": user.email.lower()})
    return {"favorites": (doc or {}).get("favorite_voices") or []}


@api.post("/studio/voices/favorites")
async def studio_voices_add_favorite(
    payload: FavoriteVoiceRequest,
    user: AuthUser = Depends(current_user),
):
    require_studio(user)
    vid = (payload.voice_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="voice_id required")
    await db.buyers.update_one(
        {"email": user.email.lower()},
        {
            "$addToSet": {"favorite_voices": vid},
            "$setOnInsert": {
                "email": user.email.lower(),
                "addedAt": datetime.now(timezone.utc).isoformat(),
                "source": "studio",
            },
            "$set": {"updatedAt": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )
    return {"ok": True}


@api.delete("/studio/voices/favorites/{voice_id}")
async def studio_voices_remove_favorite(
    voice_id: str,
    user: AuthUser = Depends(current_user),
):
    require_studio(user)
    await db.buyers.update_one(
        {"email": user.email.lower()},
        {
            "$pull": {"favorite_voices": voice_id},
            "$set": {"updatedAt": datetime.now(timezone.utc).isoformat()},
        },
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Avatar favorites — pinned avatars per user, stored in
# db.buyers.favorite_avatars. Same shape as voice favorites; with 1281 HeyGen
# avatars available, pinning the 5-10 the user actually uses saves scrolling.
# ---------------------------------------------------------------------------
class FavoriteAvatarRequest(BaseModel):
    avatar_id: str


@api.get("/studio/avatars/favorites")
async def studio_avatars_favorites(user: AuthUser = Depends(current_user)):
    require_studio(user)
    doc = await db.buyers.find_one({"email": user.email.lower()})
    return {"favorites": (doc or {}).get("favorite_avatars") or []}


@api.post("/studio/avatars/favorites")
async def studio_avatars_add_favorite(
    payload: FavoriteAvatarRequest,
    user: AuthUser = Depends(current_user),
):
    require_studio(user)
    aid = (payload.avatar_id or "").strip()
    if not aid:
        raise HTTPException(status_code=400, detail="avatar_id required")
    await db.buyers.update_one(
        {"email": user.email.lower()},
        {
            "$addToSet": {"favorite_avatars": aid},
            "$setOnInsert": {
                "email": user.email.lower(),
                "addedAt": datetime.now(timezone.utc).isoformat(),
                "source": "studio",
            },
            "$set": {"updatedAt": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )
    return {"ok": True}


@api.delete("/studio/avatars/favorites/{avatar_id}")
async def studio_avatars_remove_favorite(
    avatar_id: str,
    user: AuthUser = Depends(current_user),
):
    require_studio(user)
    await db.buyers.update_one(
        {"email": user.email.lower()},
        {
            "$pull": {"favorite_avatars": avatar_id},
            "$set": {"updatedAt": datetime.now(timezone.utc).isoformat()},
        },
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Kokoro TTS voices (static curated list — fal.ai documents these)
# ---------------------------------------------------------------------------
KOKORO_VOICES = [
    {"id": "af_bella", "name": "Bella", "gender": "female", "language": "en-US"},
    {"id": "af_nicole", "name": "Nicole", "gender": "female", "language": "en-US"},
    {"id": "af_sarah", "name": "Sarah", "gender": "female", "language": "en-US"},
    {"id": "af_sky", "name": "Sky", "gender": "female", "language": "en-US"},
    {"id": "am_adam", "name": "Adam", "gender": "male", "language": "en-US"},
    {"id": "am_michael", "name": "Michael", "gender": "male", "language": "en-US"},
    {"id": "bf_emma", "name": "Emma", "gender": "female", "language": "en-GB"},
    {"id": "bf_isabella", "name": "Isabella", "gender": "female", "language": "en-GB"},
    {"id": "bm_george", "name": "George", "gender": "male", "language": "en-GB"},
    {"id": "bm_lewis", "name": "Lewis", "gender": "male", "language": "en-GB"},
]


# Kokoro voice ID prefix → fal.ai submodel mapping. af_/am_ are American
# English, bf_/bm_ British English. Sending a British voice to the American
# endpoint returns a 400 — confirmed via the iter-13 preload run where 4/10
# voices failed before the per-prefix routing was added.
def _kokoro_endpoint(voice_id: str) -> str:
    prefix = (voice_id or "")[:2].lower()
    if prefix in ("bf", "bm"):
        return "fal-ai/kokoro/british-english"
    return "fal-ai/kokoro/american-english"


# Expose FAL_KEY for fal_client (used for storage uploads).
if FAL_API_KEY:
    os.environ["FAL_KEY"] = FAL_API_KEY

# Static ffmpeg binary bundled with imageio_ffmpeg — survives pod restarts
# where an apt-installed ffmpeg would be wiped. Used for Ken Burns + stock-
# clip trimming inside _make_kenburns_mp4 and _trim_stock_video below.
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()


async def _probe_audio_duration_s(audio_url: str, fallback_s: float) -> float:
    """Return the true audio length in seconds. Downloads the WAV briefly and
    reads its native header via the stdlib `wave` module — works for any
    Kokoro response without needing a separate ffprobe binary. Falls back to
    the script-based estimate on any failure."""
    tmp = None
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cli:
            r = await cli.get(audio_url)
            if r.status_code != 200 or not r.content:
                return fallback_s
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(r.content)
        tmp.flush()
        tmp.close()
        with wave.open(tmp.name, "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 24000
            return frames / float(rate)
    except Exception:
        return fallback_s
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass


# Ken Burns presets — alternating zoom/pan patterns so consecutive scenes feel
# cinematic instead of identical. Each entry is an ffmpeg `zoompan` arg suffix
# (the leading `scale=` is built per-aspect below). `d` is the per-scene frame
# count — substituted at call time. fps stays at 30 so duration math is clean.
_KENBURNS_PRESETS = [
    # zoom in centered
    "z='min(zoom+0.0012,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # zoom in + drift right
    "z='min(zoom+0.0010,1.15)':x='iw/2-(iw/zoom/2)+on*1.2':y='ih/2-(ih/zoom/2)'",
    # zoom in + drift up
    "z='min(zoom+0.0010,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)-on*1.0'",
    # zoom in + drift left
    "z='min(zoom+0.0010,1.15)':x='iw/2-(iw/zoom/2)-on*1.2':y='ih/2-(ih/zoom/2)'",
    # zoom out from 1.18 → 1.0
    "z='if(lte(zoom,1.0),1.18,max(zoom-0.0013,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
]


async def _make_kenburns_mp4(image_url: str, aspect: str, duration_ms: int, scene_idx: int) -> Optional[str]:
    """Download a still image, render a short MP4 with subtle ken-burns motion
    (zoom + drift), upload it to fal storage, return the public URL.
    Returns None on any failure so the caller can fall back gracefully."""
    duration_s = max(1.5, duration_ms / 1000.0)
    fps = 30
    total_frames = int(round(duration_s * fps))
    # Output canvas matches the render aspect — 1280x720 for 16:9, 720x1280 for 9:16.
    if aspect == "9_16":
        out_w, out_h = 720, 1280
        pre_scale = "scale=864:1536:force_original_aspect_ratio=increase,crop=864:1536"
    else:
        out_w, out_h = 1280, 720
        pre_scale = "scale=1536:864:force_original_aspect_ratio=increase,crop=1536:864"

    preset = _KENBURNS_PRESETS[scene_idx % len(_KENBURNS_PRESETS)]
    # Two-step framerate alignment — the historical flicker bug came from
    # `zoompan` defaulting to 25fps internally while we output at 30fps.
    # We now:
    #   1) tell ffmpeg the looped still is a 30fps stream via -framerate before -i
    #   2) compute zoompan's `d` against that same 30fps cadence
    #   3) tack `fps=30` on the END of the filter chain so any internal
    #      drift gets resampled cleanly without frame-duplication judder.
    vf = f"{pre_scale},zoompan={preset}:d={total_frames}:s={out_w}x{out_h}:fps={fps},fps={fps}"

    tmpdir = tempfile.mkdtemp(prefix="kburns_")
    src = os.path.join(tmpdir, "src")
    dst = os.path.join(tmpdir, "out.mp4")
    try:
        # Download image
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cli:
            r = await cli.get(image_url)
            if r.status_code != 200 or not r.content:
                return None
            with open(src, "wb") as f:
                f.write(r.content)
        # Render via ffmpeg in a worker thread so we don't block the event loop.
        cmd = [
            FFMPEG_BIN, "-y", "-loglevel", "error",
            # Critical for zoompan stability: declare an explicit 30fps input
            # framerate for the looped still. Without this, zoompan's internal
            # 25fps default fights with the 30fps output and produces visible
            # judder/flicker every ~5 frames as ffmpeg duplicates frames to
            # bridge the gap. Reported by Charity after iter 21 t2v rollout.
            "-framerate", str(fps),
            "-loop", "1", "-i", src,
            "-vf", vf,
            "-t", f"{duration_s:.2f}",
            "-r", str(fps),
            # `medium` preset + crf 19 keeps the still-source motion crisp.
            # `veryfast` was visibly soft on the panel borders (especially
            # on 9:16 portrait crops where the zoompan reaches max zoom).
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            dst,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0 or not os.path.exists(dst):
            logger.warning(f"[kburns] ffmpeg failed scene={scene_idx} rc={proc.returncode} stderr={err.decode()[-300:]}")
            return None
        # Upload to fal storage (sync API — run in default executor so we don't block).
        loop = asyncio.get_event_loop()
        fal_url = await loop.run_in_executor(None, fal_client.upload_file, dst)
        return fal_url
    except Exception as exc:
        logger.warning(f"[kburns] scene={scene_idx} exception: {type(exc).__name__}: {exc}")
        return None
    finally:
        try:
            for f in (src, dst):
                if os.path.exists(f):
                    os.unlink(f)
            os.rmdir(tmpdir)
        except Exception:
            pass


async def _trim_stock_video(video_url: str, aspect: str, duration_ms: int, scene_idx: int) -> Optional[str]:
    """Download a stock video (Pexels/Pixabay), trim to `duration_ms`, scale +
    crop to match the output aspect, upload to fal storage, return the URL.
    fal.ai's compose IGNORES the keyframe `duration` for video-type keyframes
    and always plays the source at its native length — so we have to pre-cut
    every stock clip ourselves to keep the timeline aligned with the audio."""
    duration_s = max(1.5, duration_ms / 1000.0)
    if aspect == "9_16":
        out_w, out_h = 720, 1280
    else:
        out_w, out_h = 1280, 720
    # Plain scale + center-crop preserves the stock clip's NATIVE motion. The
    # earlier version stacked a `zoompan` filter on top, which is a still-image
    # ken-burns filter — applied to a video input it freezes the first frame
    # and pans on it, killing the actual video motion. Reported by Charity
    # ("the b-roll video clips ... aren't moving like video clips, they look
    # like still images"). The clip is already a real video; just fit it to
    # the output frame and let it play. `fps=30` resamples 24/25/59.94/60-fps
    # sources to a consistent cadence — without it, mixing source framerates
    # produces visible micro-stutter via uneven frame duplication.
    vf = (
        f"fps=30,"
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h}"
    )
    tmpdir = tempfile.mkdtemp(prefix="trim_")
    src = os.path.join(tmpdir, "src.mp4")
    dst = os.path.join(tmpdir, "out.mp4")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as cli:
            r = await cli.get(video_url)
            if r.status_code != 200 or not r.content:
                return None
            with open(src, "wb") as f:
                f.write(r.content)
        cmd = [
            FFMPEG_BIN, "-y", "-loglevel", "error",
            "-fflags", "+genpts",        # regenerate clean PTS — fixes hitch at stream_loop seam
            "-stream_loop", "-1",        # loop short sources so the scene fills its slot
            "-ss", "0", "-i", src,
            "-t", f"{duration_s:.2f}",
            "-an",                       # drop source audio — we use Kokoro's voiceover
            "-vf", vf,
            # `-preset fast` + `-crf 21` produces visibly smoother motion on
            # fast-moving stock content (traffic, water, sports) than the old
            # `veryfast` no-crf path which dropped motion vectors aggressively.
            "-c:v", "libx264", "-preset", "fast", "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            dst,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0 or not os.path.exists(dst):
            logger.warning(f"[trim] ffmpeg failed scene={scene_idx} rc={proc.returncode} stderr={err.decode()[-300:]}")
            return None
        loop = asyncio.get_event_loop()
        fal_url = await loop.run_in_executor(None, fal_client.upload_file, dst)
        return fal_url
    except Exception as exc:
        logger.warning(f"[trim] scene={scene_idx} exception: {type(exc).__name__}: {exc}")
        return None
    finally:
        try:
            for f in (src, dst):
                if os.path.exists(f):
                    os.unlink(f)
            os.rmdir(tmpdir)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stock-search query refinement.
# Cinematic prompts (full sentences like "Wide overhead shot of hands chopping
# vegetables on a wooden board, soft kitchen daylight, slow camera drift right")
# work beautifully for Flux / Kling / Veo / Pika. But they're TERRIBLE input
# for Pexels/Pixabay's keyword-based search: words like "wide", "overhead",
# "drift", "soft" trash relevance scores. We strip the cinematographic
# vocabulary before sending to stock libraries, leaving just the visual
# nouns + actions the user wants on screen.
# ---------------------------------------------------------------------------
_STOCK_STOPWORDS = frozenset({
    # Shot types
    "wide", "medium", "close-up", "closeup", "close", "overhead", "aerial",
    "tracking", "handheld", "static", "establishing", "macro", "pov", "shot",
    "frame", "framing", "view", "angle",
    # Camera motion
    "push", "push-in", "pull", "pull-out", "zoom", "pan", "tilt", "drift",
    "dolly", "trucking", "orbit", "rotate", "rotation", "movement", "motion",
    "camera",
    # Lighting / time-of-day modifiers
    "soft", "warm", "cool", "harsh", "diffuse", "diffused", "natural",
    "golden", "blue", "hour", "neon", "candlelit", "overcast", "sunny",
    "cloudy", "shadow", "highlight", "lit", "lighting", "glow", "glare",
    "ambient", "directional", "rim", "backlit", "silhouette",
    # Direction / orientation
    "left", "right", "forward", "backward", "up", "down", "side", "front",
    "back",
    # Generic filler
    "of", "the", "with", "and", "very", "slowly", "slow", "smooth",
    "smoothly", "gently", "subtle", "subtly", "cinematic", "shallow",
    "depth", "field", "into", "onto",
})


def _extract_stock_query(prompt: str) -> str:
    """Reduce a cinematic prompt to its high-signal stock-search keywords.

    Pexels and Pixabay match search terms against video tags (nouns, actions),
    so we keep only words that aren't shot-type/camera-motion/lighting noise.
    Result is a 3-6 word query that matches stock-library tagging far better
    than the original 8-15 word cinematic description.

    Example:
      "Wide overhead shot of hands chopping fresh vegetables on a wooden
       board, soft kitchen daylight, slow camera drift right"
      → "hands chopping fresh vegetables wooden board"
    """
    if not prompt:
        return ""
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]+", prompt.lower())
    kept = [t for t in tokens if t not in _STOCK_STOPWORDS and len(t) > 2]
    return " ".join(kept[:6])


def _score_pexels_hit(video: dict, keyword_set: set) -> int:
    """Score a Pexels video by tag/title overlap with extracted keywords."""
    haystack = " ".join([
        str(video.get("url", "")),
        str((video.get("user") or {}).get("name", "")),
        " ".join(str(t) for t in (video.get("tags") or [])),
    ]).lower()
    return sum(1 for k in keyword_set if k in haystack)


async def _auto_search_stock_url(source: str, query: str, orientation: str) -> Optional[str]:
    """Pick the best viable stock-video URL for a scene whose source is
    'pexels' / 'pixabay' / 'mix' but the user did not pre-pick a clip.

    Quality fixes over the iter-1 "take first 480-720p hit" pattern:
      1. Search query is the EXTRACTED keyword form (nouns + actions only),
         not the full cinematic prompt — Pexels matches tags, not shot
         descriptions, so "wide overhead drift" was tanking relevance.
      2. We fetch 15 candidates (was 5) and re-rank by tag/title overlap
         with the keyword set; top-ranked candidate wins.
      3. Stock resolution floor is 720p (was 480p) — no soft clips on
         modern screens. Ceiling 1080p — no 4K wasting compose time.
    """
    sources = ["pexels", "pixabay"] if source == "mix" else [source]
    search_query = _extract_stock_query(query) or query
    keyword_set = {w for w in search_query.split() if w}
    async with httpx.AsyncClient(timeout=15) as client:
        for src in sources:
            try:
                if src == "pexels" and PEXELS_API_KEY:
                    r = await client.get(
                        "https://api.pexels.com/videos/search",
                        headers={"Authorization": PEXELS_API_KEY},
                        params={"query": search_query, "orientation": orientation, "per_page": 15},
                    )
                    if r.status_code != 200:
                        continue
                    candidates = r.json().get("videos") or []
                    # Re-rank by keyword overlap in tags / title / user fields.
                    # Stable sort preserves Pexels' relevance order as tiebreak.
                    candidates.sort(key=lambda v: _score_pexels_hit(v, keyword_set), reverse=True)
                    for v in candidates:
                        files = v.get("video_files") or []
                        # 720-1080p sweet spot.
                        files.sort(key=lambda f: (f.get("height") or 0))
                        pick = next(
                            (f for f in files if 720 <= (f.get("height") or 0) <= 1080),
                            None,
                        )
                        # Fallback: if a clip only exists above 1080p, take
                        # the smallest height that's still >=720p so we
                        # never serve sub-720p to modern customers.
                        if not pick and files:
                            higher = [f for f in files if (f.get("height") or 0) >= 720]
                            pick = higher[0] if higher else None
                        if pick and pick.get("link"):
                            return pick["link"]
                elif src == "pixabay" and PIXABAY_API_KEY:
                    r = await client.get(
                        "https://pixabay.com/api/videos/",
                        params={"key": PIXABAY_API_KEY, "q": search_query, "per_page": 15},
                    )
                    if r.status_code != 200:
                        continue
                    candidates = r.json().get("hits") or []
                    candidates.sort(
                        key=lambda v: sum(1 for k in keyword_set if k in (v.get("tags") or "").lower()),
                        reverse=True,
                    )
                    for v in candidates:
                        videos = v.get("videos") or {}
                        # Pixabay tiers: tiny (240p), small (640p), medium (~960p), large (1080p).
                        # Prefer large → medium; never tiny/small (sub-720p).
                        pick = videos.get("large") or videos.get("medium")
                        if pick and pick.get("url"):
                            return pick["url"]
            except Exception as exc:
                logger.warning(f"[auto-stock] {src}/{query}: {exc}")
                continue
    return None


# --- AI Text-to-Video engines (Faceless mode, optional alternative to Flux) ---
# When a scene's effective source is "ai" AND `ai_engine != "flux"`, instead of
# generating a static Flux image + ken-burns motion, we hit one of fal.ai's
# native t2v models. The raw output is a 5-10s MP4 at the model's resolution;
# we then run it through `_trim_stock_video` to crop/scale/loop to the exact
# per-scene duration in our timeline.
T2V_ENGINES: dict = {
    # Kling 2.1 Master — premium cinematic, ~$0.30-0.50/clip. 5s or 10s only.
    "kling": {
        "model": "fal-ai/kling-video/v2.1/master/text-to-video",
        "build_payload": lambda prompt, aspect, dur_s: {
            "prompt": prompt,
            "duration": "10" if dur_s > 7 else "5",
            "aspect_ratio": "9:16" if aspect == "9_16" else "16:9",
            # Negative prompt + tighter cfg_scale lift Kling output above the
            # default "AI slop" feel. Reported live by Charity after a $30
            # render — visuals were disconnected from the script. Stronger
            # prompt adherence + explicit reject of low-quality artefacts.
            "negative_prompt": "blurry, low quality, distorted, ugly, watermark, text overlay, deformed, bad anatomy, oversaturated, grainy, jpeg artifacts, motion blur",
            "cfg_scale": 0.7,
        },
        "cost_cents": 50,
        "max_wait_s": 600,
    },
    # Veo 3.1 Fast — Google quality at half the cost. 4/6/8s. No audio (we
    # have Kokoro voiceover, so generate_audio is forced off).
    "veo3": {
        "model": "fal-ai/veo3.1/fast",
        "build_payload": lambda prompt, aspect, dur_s: {
            "prompt": prompt,
            "duration": "8s" if dur_s > 6 else ("6s" if dur_s > 4 else "4s"),
            "aspect_ratio": "9:16" if aspect == "9_16" else "16:9",
            "resolution": "720p",
            "generate_audio": False,
            "negative_prompt": "blurry, low quality, distorted, ugly, watermark, text overlay, deformed, bad anatomy, oversaturated, grainy, jpeg artifacts",
        },
        "cost_cents": 100,  # ~$1/clip @ 8s standard pricing
        "max_wait_s": 900,
    },
    # Pika 2.1 — flat $0.40/clip, supports many aspect ratios. Charity's best
    # subjective t2v experience so far; bias the default UX here once we're
    # confident in the prompt-engineering pipeline.
    "pika": {
        "model": "fal-ai/pika/v2.1/text-to-video",
        "build_payload": lambda prompt, aspect, dur_s: {
            "prompt": prompt,
            "duration": 10 if dur_s > 7 else 5,
            "aspect_ratio": "9:16" if aspect == "9_16" else "16:9",
            "resolution": "720p",
            "negative_prompt": "blurry, low quality, distorted, ugly, watermark, text overlay, deformed, bad anatomy, oversaturated, grainy, jpeg artifacts",
        },
        "cost_cents": 40,
        "max_wait_s": 600,
    },
}


async def _fal_t2v_generate(engine: str, prompt: str, aspect: str, duration_ms: int) -> Optional[str]:
    """Submit a prompt to one of the AI text-to-video engines (Kling/Veo/Pika)
    on fal.ai and poll for completion. Returns the raw MP4 URL or None on any
    failure. Per-scene; the caller is expected to trim/scale/loop the result
    to the exact duration via `_trim_stock_video`."""
    cfg = T2V_ENGINES.get(engine)
    fal_key = _effective_fal_key()
    if not cfg or not fal_key:
        return None
    fal_headers = {"Authorization": f"Key {fal_key}"}
    payload = cfg["build_payload"](prompt, aspect, max(1.0, duration_ms / 1000.0))
    model_id = cfg["model"]
    max_wait_s = cfg["max_wait_s"]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            sub = await client.post(
                f"https://queue.fal.run/{model_id}",
                headers=fal_headers,
                json=payload,
            )
            if sub.status_code not in (200, 202):
                logger.warning(f"[t2v] {engine} submit FAIL {sub.status_code}: {sub.text[:200]}")
                return None
            sub_body = sub.json()
            status_url = sub_body.get("status_url")
            result_url = sub_body.get("response_url")
            if not status_url or not result_url:
                logger.warning(f"[t2v] {engine} submit malformed: {str(sub_body)[:200]}")
                return None
            deadline = asyncio.get_event_loop().time() + max_wait_s
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(2)  # was 4s — snappier completion detection
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
                    logger.warning(f"[t2v] {engine} FAILED: {stat.text[:200]}")
                    return None
            logger.warning(f"[t2v] {engine} polling timed out after {max_wait_s}s")
            return None
    except Exception as exc:
        logger.warning(f"[t2v] {engine} exception: {type(exc).__name__}: {exc}")
        return None


async def _trim_t2v_clip(video_url: str, duration_ms: int, scene_idx: int) -> Optional[str]:
    """Trim a fresh text-to-video output to the exact per-scene duration WITHOUT
    re-scaling or re-cropping. The t2v engines (Kling/Veo/Pika) already emit
    the requested aspect ratio natively — running them through the stock-clip
    normalizer's scale+crop pipeline was double-encoding the output, softening
    detail, and occasionally squashing the aspect when the source dimensions
    were slightly off-spec (e.g. 1080x1920 → re-cropped to 720x1280 with a
    different DAR). Reported by Charity post-iter 21: 'occasionally aspect
    ratio was wrong... AI slop feel'."""
    duration_s = max(1.5, duration_ms / 1000.0)
    tmpdir = tempfile.mkdtemp(prefix="t2vtrim_")
    src = os.path.join(tmpdir, "src.mp4")
    dst = os.path.join(tmpdir, "out.mp4")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as cli:
            r = await cli.get(video_url)
            if r.status_code != 200 or not r.content:
                return None
            with open(src, "wb") as f:
                f.write(r.content)
        cmd = [
            FFMPEG_BIN, "-y", "-loglevel", "error",
            "-fflags", "+genpts",
            "-stream_loop", "-1",   # loop in case scene is longer than the t2v clip's max (10s)
            "-ss", "0", "-i", src,
            "-t", f"{duration_s:.2f}",
            "-an",
            # NO -vf — we deliberately preserve the t2v engine's native
            # resolution, framerate, and aspect. The engine was already told
            # which aspect to render in; trust its output.
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            dst,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0 or not os.path.exists(dst):
            logger.warning(f"[t2v-trim] ffmpeg failed scene={scene_idx} rc={proc.returncode} stderr={err.decode()[-300:]}")
            return None
        loop = asyncio.get_event_loop()
        fal_url = await loop.run_in_executor(None, fal_client.upload_file, dst)
        return fal_url
    except Exception as exc:
        logger.warning(f"[t2v-trim] scene={scene_idx} exception: {type(exc).__name__}: {exc}")
        return None
    finally:
        try:
            for f in (src, dst):
                if os.path.exists(f):
                    os.unlink(f)
            os.rmdir(tmpdir)
        except Exception:
            pass


async def _make_t2v_clip(prompt: str, aspect: str, duration_ms: int, engine: str, scene_idx: int) -> Optional[str]:
    """Generate an AI text-to-video clip via fal.ai (Kling/Veo/Pika), then
    trim it to fit the exact `duration_ms` slot WITHOUT scale/crop. The t2v
    engines already emit the requested aspect natively — see _trim_t2v_clip."""
    raw_url = await _fal_t2v_generate(engine, prompt, aspect, duration_ms)
    if not raw_url:
        return None
    return await _trim_t2v_clip(raw_url, duration_ms, scene_idx)


# --- AI Image-to-Video (Kling i2v) -----------------------------------------
# Replaces the previous "Flux still → ken-burns'd MP4" path with REAL AI
# motion. Architecture:
#   1. Flux generates the still (already done in step 2 of _run_render_faceless,
#      and the URL is content-hash cached in db.flux_cache).
#   2. Kling i2v takes that still + the original scene prompt and produces a
#      5-or-10s MP4 with real camera/subject motion (vs the previous fake
#      ken-burns zoom).
#   3. We trim the clip to the exact `duration_ms` slot via _trim_t2v_clip.
#   4. Result is cached in db.kling_i2v_cache keyed by
#      sha256(flux_url|aspect|duration_bucket) so re-renders of the same
#      script + aspect become instant (Flux cache already does the same for
#      step 1).
#
# Cost: Kling 2.1 STANDARD i2v ≈ $0.25 / 5s clip, $0.50 / 10s clip on fal.
# For a typical 8-scene Faceless render that's ~$2 extra in spend — well
# under the silent $5 backstop in _run_render_faceless.
#
# Fallback: if Kling fails or times out, the caller falls back to the
# original ken-burns ffmpeg path so a single i2v outage doesn't kill the
# whole render.
KLING_I2V_MODEL = "fal-ai/kling-video/v2.1/standard/image-to-video"
KLING_I2V_COST_CENTS_5S = 25
KLING_I2V_COST_CENTS_10S = 50
KLING_I2V_MAX_WAIT_S = 600


async def _fal_kling_i2v_generate(
    image_url: str,
    prompt: str,
    aspect: str,
    duration_ms: int,
) -> Optional[str]:
    """Submit a Flux still + prompt to Kling 2.1 standard i2v and poll for
    the resulting MP4. Returns the raw MP4 URL or None on any failure.
    Same queue/poll pattern as `_fal_t2v_generate` — kept separate so the
    duration buckets + the cost telemetry stay clean per engine."""
    fal_key = _effective_fal_key()
    if not fal_key or not image_url:
        return None
    fal_headers = {"Authorization": f"Key {fal_key}"}
    # Kling supports 5 or 10 seconds only; round up so we always have at least
    # `duration_ms` of source material to trim from.
    duration_s_str = "10" if (duration_ms / 1000.0) > 5.5 else "5"
    payload = {
        "prompt": prompt,
        "image_url": image_url,
        "duration": duration_s_str,
        "aspect_ratio": "9:16" if aspect == "9_16" else "16:9",
        # Looser cfg lets Kling express creative motion without ignoring the
        # source still. 0.5 is fal's default; we lift to 0.6 to keep the
        # output closer to the prompt's described action.
        "cfg_scale": 0.6,
        "negative_prompt": (
            "blurry, low quality, distorted, ugly, watermark, text overlay, "
            "deformed, bad anatomy, oversaturated, grainy, jpeg artifacts, "
            "static image, motionless"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            sub = await client.post(
                f"https://queue.fal.run/{KLING_I2V_MODEL}",
                headers=fal_headers,
                json=payload,
            )
            if sub.status_code not in (200, 202):
                logger.warning(f"[i2v] kling submit FAIL {sub.status_code}: {sub.text[:200]}")
                return None
            sub_body = sub.json()
            status_url = sub_body.get("status_url")
            result_url = sub_body.get("response_url")
            if not status_url or not result_url:
                logger.warning(f"[i2v] kling submit malformed: {str(sub_body)[:200]}")
                return None
            deadline = asyncio.get_event_loop().time() + KLING_I2V_MAX_WAIT_S
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
                    logger.warning(f"[i2v] kling FAILED: {stat.text[:200]}")
                    return None
            logger.warning(f"[i2v] kling polling timed out after {KLING_I2V_MAX_WAIT_S}s")
            return None
    except Exception as exc:
        logger.warning(f"[i2v] kling exception: {type(exc).__name__}: {exc}")
        return None


async def _make_i2v_clip(
    image_url: str,
    prompt: str,
    aspect: str,
    duration_ms: int,
    scene_idx: int,
) -> Optional[str]:
    """Cache-first Kling i2v generation + trim to exact per-scene duration.
    Cache key = sha256(flux_url|aspect|duration_bucket). Duration bucket is
    "5" or "10" so cache hits even when per-scene durations vary by ms.
    Returns the final MP4 URL (trimmed to `duration_ms`) or None on failure."""
    if not image_url:
        return None
    import hashlib  # noqa: PLC0415
    duration_bucket = "10" if (duration_ms / 1000.0) > 5.5 else "5"
    cache_key = "kling_i2v:" + hashlib.sha256(
        f"{image_url}|{aspect}|{duration_bucket}".encode("utf-8")
    ).hexdigest()[:32]
    cached = await db.kling_i2v_cache.find_one({"_id": cache_key})
    raw_url = cached.get("raw_url") if cached else None
    if not raw_url:
        raw_url = await _fal_kling_i2v_generate(image_url, prompt, aspect, duration_ms)
        if raw_url:
            await db.kling_i2v_cache.update_one(
                {"_id": cache_key},
                {"$set": {
                    "raw_url": raw_url,
                    "image_url": image_url,
                    "aspect": aspect,
                    "duration_bucket": duration_bucket,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
    if not raw_url:
        return None
    # Trim the (possibly cached) raw Kling clip down to the exact ms slot
    # WITHOUT touching the resolution — Kling already emits the requested
    # aspect natively, so _trim_t2v_clip (which is `-c:v copy` style) is the
    # right fit vs _trim_stock_video (which scales+crops).
    return await _trim_t2v_clip(raw_url, duration_ms, scene_idx)


    return await _trim_t2v_clip(raw_url, duration_ms, scene_idx)


# --- Caption burn-in (second-pass fal.ai auto-subtitle) ---------------------
# After the main `fal-ai/ffmpeg-api/compose` finishes stitching the video +
# voiceover, we feed the resulting MP4 to `fal-ai/workflow-utilities/auto-
# subtitle` which:
#   1. Re-extracts the audio from the composed video,
#   2. Transcribes it with word-level timing (ElevenLabs STT under the hood),
#   3. Burns styled subtitles onto the video and returns a new MP4 URL.
#
# We expose 3 caption styles in the UI that map to concrete preset objects
# below. The render request stores `caption_style` (default "boxed") so
# saved history docs replay the same look on regen.
#
# Cost: roughly $0.10 / video for short renders (TikTok-length). Charged
# once per render when `captions=True`. Soft-fails on errors so a caption
# outage never blocks shipping the underlying render.
AUTO_SUBTITLE_MODEL = "fal-ai/workflow-utilities/auto-subtitle"
CAPTION_BURN_COST_CENTS = 10  # ~$0.10/render
CAPTION_BURN_MAX_WAIT_S = 600

# v1.15.0 — caption-burn-in pipeline moved into its own module so server.py
# stays manageable. The presets + helper are re-exported here for any
# legacy import path that still references them via `server.CAPTION_*` or
# `server._burn_in_captions`.
from caption_burn_in import (  # noqa: E402
    CAPTION_STYLE_PRESETS,
    CAPTION_POSITION_OVERRIDES,
    burn_in_captions as _burn_in_captions_impl,
)


async def _burn_in_captions(video_url: str, style_key: str, position_key: str = "bottom") -> Optional[str]:
    """Compat shim — delegates to caption_burn_in.burn_in_captions, injecting
    the BYOK-aware fal key resolver so customer keys still take precedence
    inside the active render coroutine."""
    return await _burn_in_captions_impl(
        video_url,
        style_key,
        position_key,
        fal_key_provider=_effective_fal_key,
    )

# --- Sentence-aware script splitter ----------------------------------------
# Each "beat" is one natural pause in the voiceover (sentence or em-dash/comma
# split for runs longer than 25 words). Used by:
#   - `/studio/broll-prompts` to decide how many visual prompts to generate
#   - `_run_render_faceless` to allocate per-scene video duration proportional
#     to the words each scene's visual covers, so cuts always land on a real
#     pause in the audio instead of mid-sentence.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'\u201c])")
_LONG_SENTENCE_WORDS = 25


def split_script_into_beats(script: str, *, min_beats: int = 3, max_beats: int = 12) -> list[tuple[str, int]]:
    """Return a list of (beat_text, word_count) tuples covering the whole script.

    Algorithm:
      1. Split on `.!?` followed by a capital — that's a real sentence boundary.
      2. Any sub-sentence >25 words gets further split on em-dash, then comma.
      3. If we ended up with < min_beats (very short script), evenly slice the
         words into exactly min_beats chunks so the storyboard still has variety.
      4. If we ended up with > max_beats, repeatedly merge the shortest beat
         into its neighbour until we hit max_beats — keeps long sentences intact.
    """
    text = re.sub(r"\s+", " ", (script or "").strip())
    if not text:
        return []

    raw = _SENTENCE_SPLIT_RE.split(text)
    beats: list[str] = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        words = s.split()
        if len(words) <= _LONG_SENTENCE_WORDS:
            beats.append(s)
            continue
        # Long run-on — try em-dash, then comma. Drop fragments shorter than 3 words.
        parts = re.split(r"\s*[—–-]{1,2}\s*", s)
        if len(parts) == 1:
            parts = re.split(r",\s+", s)
        sub = [p.strip() for p in parts if p.strip() and len(p.split()) >= 3]
        beats.extend(sub if sub else [s])

    # Empty (no terminating punctuation) — treat the whole thing as one beat.
    if not beats:
        beats = [text]

    words = text.split()
    total_words = len(words)

    # Pad up to min_beats by evenly slicing words.
    if len(beats) < min_beats and total_words >= min_beats:
        chunk = total_words // min_beats
        beats = []
        for i in range(min_beats):
            start = i * chunk
            end = total_words if i == min_beats - 1 else (i + 1) * chunk
            beats.append(" ".join(words[start:end]))

    # Trim down to max_beats by merging the shortest beat into its neighbour.
    while len(beats) > max_beats:
        sizes = [len(b.split()) for b in beats]
        min_idx = min(range(len(sizes)), key=lambda i: sizes[i])
        if min_idx == 0:
            beats[0] = beats[0] + " " + beats[1]
            del beats[1]
        else:
            beats[min_idx - 1] = beats[min_idx - 1] + " " + beats[min_idx]
            del beats[min_idx]

    return [(b, max(1, len(b.split()))) for b in beats]




@api.get("/studio/tts-voices")
async def studio_tts_voices(user: AuthUser = Depends(current_user)):
    require_studio(user)
    # Hydrate from the voice_samples cache so the picker can show previews
    cached = {
        doc["voice_id"]: doc.get("audio_url")
        async for doc in db.voice_samples.find({"engine": "kokoro"})
    }
    out = []
    for v in KOKORO_VOICES:
        out.append({**v, "preview_audio": cached.get(v["id"])})
    return {"voices": out}


@api.post("/studio/tts-voices/preload")
async def studio_tts_voices_preload(user: AuthUser = Depends(current_user)):
    """Admin-only: generate a 5-second preview clip for each Kokoro voice
    and cache the result URL in `db.voice_samples`. Idempotent — voices that
    already have a cached preview are skipped. Costs ~$0.05 total for all 10
    voices, one-time per deployment."""
    require_studio(user)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    if not FAL_API_KEY:
        raise HTTPException(status_code=500, detail="fal.ai key missing")
    fal_headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}
    sample_text = "Hello, this is a quick preview of how my voice sounds when narrating your videos."

    existing = {doc["voice_id"] async for doc in db.voice_samples.find({"engine": "kokoro"})}
    to_generate = [v for v in KOKORO_VOICES if v["id"] not in existing]

    async def gen_one(voice):
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://fal.run/{_kokoro_endpoint(voice['id'])}",
                headers=fal_headers,
                json={"prompt": sample_text, "voice": voice["id"]},
            )
            if r.status_code != 200:
                return voice["id"], None
            audio_url = r.json().get("audio_url") or r.json().get("audio", {}).get("url")
            if audio_url:
                await db.voice_samples.update_one(
                    {"engine": "kokoro", "voice_id": voice["id"]},
                    {"$set": {
                        "audio_url": audio_url,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
            return voice["id"], audio_url

    results = await asyncio.gather(*[gen_one(v) for v in to_generate])
    return {
        "generated": len([r for r in results if r[1]]),
        "skipped": len(KOKORO_VOICES) - len(to_generate),
        "failed": len([r for r in results if not r[1]]),
        "voice_ids": [r[0] for r in results if r[1]],
    }


# ---------------------------------------------------------------------------
# Stock search — Pexels + Pixabay
# ---------------------------------------------------------------------------
@api.get("/studio/stock-search")
async def studio_stock_search(
    source: str = Query(...),
    q: str = Query(...),
    orientation: str = Query("portrait"),  # portrait | landscape
    user: AuthUser = Depends(current_user),
):
    require_studio(user)
    if source not in ("pexels", "pixabay"):
        raise HTTPException(status_code=400, detail="Bad source")

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        if source == "pexels":
            if not PEXELS_API_KEY:
                raise HTTPException(status_code=500, detail="Pexels key missing")
            r = await client.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                # 40 results gives users a real choice (previously 12 made the
                # picker feel anemic — reported by Charity). Pexels accepts up
                # to 80 per page; 40 keeps payload size sane while tripling
                # variety. No explicit sort param — Pexels orders by relevance
                # which already prioritises popular high-engagement clips.
                params={"query": q, "orientation": orientation, "per_page": 40},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="Pexels error")
            for v in r.json().get("videos") or []:
                # Choose the SD or HD file that matches orientation
                files = v.get("video_files") or []
                files.sort(key=lambda f: (f.get("height") or 0))
                pick = next((f for f in files if (f.get("height") or 0) >= 480), files[-1] if files else None)
                if not pick:
                    continue
                results.append({
                    "id": f"pex-{v.get('id')}",
                    "thumb": v.get("image"),
                    "video_url": pick.get("link"),
                    "duration": v.get("duration"),
                    "width": pick.get("width"),
                    "height": pick.get("height"),
                    "source": "pexels",
                })
        else:  # pixabay
            if not PIXABAY_API_KEY:
                raise HTTPException(status_code=500, detail="Pixabay key missing")
            r = await client.get(
                "https://pixabay.com/api/videos/",
                # `order=popular` ranks by community engagement (lifetime views +
                # likes) which is a far better quality signal than Pixabay's
                # default `popular-by-week` (skews to whatever a few users
                # spammed last 7 days). 50 results = 4x what we had before.
                params={
                    "key": PIXABAY_API_KEY,
                    "q": q,
                    "per_page": 50,
                    "order": "popular",
                    "safesearch": "true",
                },
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="Pixabay error")
            for v in r.json().get("hits") or []:
                videos = v.get("videos") or {}
                # Prefer `medium` for play (smaller files), but fall through to
                # other sizes if medium is missing on a given clip.
                pick = videos.get("medium") or videos.get("small") or videos.get("large") or videos.get("tiny")
                if not pick:
                    continue
                # Pixabay's API moved off Vimeo CDN — every size object now
                # carries its own `thumbnail` URL. The old `picture_id` field
                # is gone, which is why every Pixabay card was rendering as
                # a blank tile until this fix.
                thumb = pick.get("thumbnail")
                if not thumb:
                    # Best-effort fallback: any other size's thumbnail.
                    for sz in ("large", "medium", "small", "tiny"):
                        cand = (videos.get(sz) or {}).get("thumbnail")
                        if cand:
                            thumb = cand
                            break
                results.append({
                    "id": f"pix-{v.get('id')}",
                    "thumb": thumb,
                    "video_url": pick.get("url"),
                    "duration": v.get("duration"),
                    "width": pick.get("width"),
                    "height": pick.get("height"),
                    "source": "pixabay",
                })

    return {"results": results}


# ---------------------------------------------------------------------------
# Studio renders
# ---------------------------------------------------------------------------
async def _log_activity(typ: str, email: str, detail: dict):
    await db.activity.insert_one({
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": typ,
        "email": email,
        "detail": detail,
    })


async def _run_render(job_id: str):
    """Dispatch to the per-mode render pipeline."""
    job = await db.renders.find_one({"id": job_id})
    if not job:
        return
    mode = job.get("mode")
    try:
        if mode == "avatar":
            await _run_render_avatar(job)
        elif mode == "faceless":
            await _run_render_faceless(job)
        elif mode == "composite":
            await _run_render_composite(job)
        else:
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {"status": "failed", "error": f"Unknown mode: {mode}"}},
            )
    except Exception as exc:  # noqa: BLE001  — pipeline must never crash worker
        await db.renders.update_one(
            {"id": job_id},
            {"$set": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    # Group B refund-on-failure. Re-read the job to see the FINAL status the
    # pipeline persisted (the inner functions also set status=failed on
    # their own error paths, not just the catch above). If the render
    # didn't complete, refund the quota slot the gate consumed at queue
    # time. Founders/dev/grant emails are no-op'd inside _refund_quota_slot.
    final = await db.renders.find_one({"id": job_id}, {"status": 1, "user_email": 1, "mode": 1, "estimated_cost_cents": 1})
    if final and final.get("status") == "failed":
        await _refund_quota_slot(
            email=final.get("user_email") or "",
            mode=final.get("mode") or "",
            estimated_cents=int(final.get("estimated_cost_cents") or 0),
        )


# ---------------------------------------------------------------------------
# Cost estimation. Numbers below are conservative ceiling estimates derived
# from public pricing pages (HeyGen $0.30 / min talking-head, fal.ai Kokoro
# TTS ~$0.005 / 1k chars, Flux 1.1 pro ~$0.04 / image, ffmpeg compose ~free
# on fal.ai). Conservative because we'd rather reject a borderline render
# than surprise-charge the user above the cap.
# ---------------------------------------------------------------------------
def _estimate_duration_seconds(script: str) -> float:
    """Approximate spoken duration from script word count at ~150 wpm."""
    words = len([w for w in script.split() if w.strip()])
    return max(5.0, (words / 150.0) * 60.0)


def estimate_render_cost_cents(payload: RenderRequest) -> int:
    """Conservative cost estimate (in cents) for a real render of this payload."""
    duration_s = _estimate_duration_seconds(payload.script)
    duration_min = duration_s / 60.0
    cents = 0.0

    if payload.mode == "avatar":
        # HeyGen $0.30/min + 5c flat overhead
        cents += duration_min * 30.0 + 5.0
    elif payload.mode == "faceless":
        # Kokoro TTS + per-scene visuals + compose
        scene_count = max(1, len(payload.scenes) or int(duration_s / 8))
        # ~$0.005 / 1k chars for Kokoro-class TTS — coefficient deliberately
        # conservative (real renders may cost less but we'd rather reject
        # a borderline payload than surprise-charge the user above the cap).
        cents += (len(payload.script) / 1000.0) * 5.0  # TTS
        # Per-scene cost depends on whether AI scenes use Flux 1.1 Pro (static
        # image + ken-burns) or one of the premium text-to-video engines.
        engine = (payload.ai_engine or "flux").lower()
        if engine in T2V_ENGINES:
            # Worst case: every scene is an AI t2v clip. Real renders may mix
            # in cheaper stock — but we estimate the ceiling for the circuit
            # breaker so a 12-scene Veo render doesn't sneak past us.
            ai_scenes = sum(1 for s in payload.scenes if (s.get("source") or payload.broll_source) == "ai") or scene_count
            cents += ai_scenes * T2V_ENGINES[engine]["cost_cents"]
            stock_scenes = max(0, scene_count - ai_scenes)
            cents += stock_scenes * 1.0  # stock search is essentially free
        else:
            # Default Flux (id="flux") upgrades to Kling i2v real motion at
            # ~$0.29/scene. Flux Static (id="flux_static") is the cheap
            # ken-burns-only path at ~$0.04/scene. Charity approved both
            # paths in the 2026-02-22 bundle so cost-conscious renders can
            # still ship with stills.
            cents += scene_count * 4.0   # Flux images (both modes)
            if engine != "flux_static":
                cents += scene_count * KLING_I2V_COST_CENTS_5S   # Kling i2v motion
        cents += 2.0                                   # compose overhead
    elif payload.mode == "composite":
        # Avatar talking-head + B-roll cutaway every N seconds
        cents += duration_min * 30.0 + 5.0             # HeyGen base
        cutaway_count = max(1, int(duration_s / max(1, payload.broll_cutaway_interval_s)))
        cents += cutaway_count * 4.0                   # Flux per cutaway
        cents += 3.0                                   # extra compose overhead
    else:
        return 0
    # Caption burn-in second pass (~$0.10) — only when explicitly enabled.
    # Charged identically for Avatar, Faceless, and Composite modes since
    # all three terminate with a single composed MP4 fed to auto-subtitle.
    if payload.captions:
        cents += CAPTION_BURN_COST_CENTS
    return int(round(cents))


# ---------------------------------------------------------------------------
# Stage walker shared by all pipelines.
# ---------------------------------------------------------------------------
async def _walk_stages(job_id: str, stages):
    for status, progress, label in stages:
        await asyncio.sleep(4.0)
        await db.renders.update_one(
            {"id": job_id},
            {"$set": {"status": status, "progress": progress, "progress_label": label}},
        )


def _finalize(job_id: str, *, ok: bool, url: Optional[str], actual_cost_cents: int):
    return db.renders.update_one(
        {"id": job_id},
        {"$set": {
            "status": "complete" if ok else "failed",
            "progress": 100,
            "progress_label": "Done" if ok else "Failed",
            "result_url": url,
            "actual_cost_cents": actual_cost_cents,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


# ---------------------------------------------------------------------------
# HeyGen Avatar pipeline — real renders only.
# Uses the HeyGen v3 /v3/videos endpoint with the documented `fit: "cover"`
# field and burn-in captions via `caption.style`.
# ---------------------------------------------------------------------------
async def _run_render_avatar(job: dict):
    job_id = job["id"]
    actual_cost_cents = 0

    # BYOK — if the buyer has saved their own HeyGen key, use it for THIS
    # render only. Lookup failures fall back to the platform key silently
    # so a stale/rotated user key never breaks the pipeline mid-flight.
    try:
        user_email = (job.get("user_email") or "").strip().lower()
        if user_email:
            user_heygen = await get_byok_key(db, user_email, "heygen")
            if user_heygen:
                _override_heygen_key_ctx.set(user_heygen)
    except Exception as exc:
        logger.warning(f"[byok] avatar key lookup failed: {type(exc).__name__}: {exc}")
    heygen_key = _effective_heygen_key()

    if not heygen_key:
        await _finalize(job_id, ok=False, url=None, actual_cost_cents=0)
        return

    # ---- Stage 1/3: voiceover ----
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {"status": "voiceover", "progress": 20, "progress_label": "Preparing voiceover…"}},
    )
    await asyncio.sleep(1.5)

    # ---- Stage 2/3: submit to HeyGen. Try v3 first (cleaner crop for Avatar
    # IV/V); on the explicit "does not support Avatar IV" error, transparently
    # fall back to the legacy v2 endpoint (Avatar III avatars). The customer
    # never sees the fallback. Captions intentionally OFF in both bodies for
    # this iteration — HeyGen-side burn-in was inconsistent across avatars
    # so we'll add captions back in a dedicated future pass. ----
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {"status": "avatar", "progress": 45, "progress_label": "Generating avatar video…"}},
    )

    video_id = None
    used_endpoint = "v3"
    async with httpx.AsyncClient(timeout=60) as client:
        v3_body = {
            "type": "avatar",
            "avatar_id": job["avatar_id"],
            "script": job["script"],
            "voice_id": job["voice_id"],
            "aspect_ratio": "9:16" if job["aspect"] == "9_16" else "16:9",
            "fit": "cover",
        }
        r = await client.post(
            "https://api.heygen.com/v3/videos",
            headers={"X-Api-Key": heygen_key, "Accept": "application/json"},
            json=v3_body,
        )
        if r.status_code == 200:
            d = (r.json() or {}).get("data") or {}
            video_id = d.get("video_id") or d.get("id")

        # Fall back to v2 on Avatar IV incompatibility, or any other v3 error.
        if not video_id:
            v3_err_text = r.text if r is not None else ""
            v2_body = {
                "video_inputs": [{
                    "character": {
                        "type": "avatar",
                        "avatar_id": job["avatar_id"],
                        "avatar_style": "normal",
                    },
                    "voice": {
                        "type": "text",
                        "voice_id": job["voice_id"],
                        "input_text": job["script"],
                    },
                }],
                "dimension": {
                    "width": 1080 if job["aspect"] == "9_16" else 1920,
                    "height": 1920 if job["aspect"] == "9_16" else 1080,
                },
                "aspect_ratio": "9:16" if job["aspect"] == "9_16" else "16:9",
            }
            r2 = await client.post(
                "https://api.heygen.com/v2/video/generate",
                headers={"X-Api-Key": heygen_key, "Accept": "application/json"},
                json=v2_body,
            )
            if r2.status_code != 200:
                await db.renders.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "error": (
                            f"HeyGen submit failed. v3: {r.status_code} {v3_err_text[:200]} "
                            f"| v2: {r2.status_code} {r2.text[:200]}"
                        ),
                        "actual_cost_cents": actual_cost_cents,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return
            video_id = ((r2.json() or {}).get("data") or {}).get("video_id")
            used_endpoint = "v2"
            if not video_id:
                await db.renders.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "error": f"HeyGen v2 returned no video_id: {r2.text[:300]}",
                        "actual_cost_cents": actual_cost_cents,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return

        # ---- Stage 3/3: poll ----
        # Per Charity's "no limits" rule, the poll window is generous: 300
        # ticks × 5s = 25 minutes. HeyGen v3 renders for premium avatars +
        # long scripts can take 10-18min; the old 5min cap was killing real
        # renders mid-stream. Progress label animates so the UI never feels
        # stuck during the long wait.
        max_ticks = 300
        for tick in range(max_ticks):
            await asyncio.sleep(5)
            # Animate the in-flight progress so it doesn't feel stuck during
            # the long HeyGen render wait. Walks 50→90% across the poll window.
            progress_now = min(90, 50 + int(tick * 40 / max_ticks))
            label_now = ("Polishing avatar…" if tick > 30
                         else "Rendering avatar frames…" if tick > 10
                         else "Finalizing voiceover…")
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {"progress": progress_now, "progress_label": label_now}},
            )
            if used_endpoint == "v3":
                s = await client.get(
                    f"https://api.heygen.com/v3/videos/{video_id}",
                    headers={"X-Api-Key": heygen_key},
                )
                d = (s.json() or {}).get("data") or {}
                if d.get("failure_code"):
                    await db.renders.update_one(
                        {"id": job_id},
                        {"$set": {
                            "status": "failed",
                            "error": f"HeyGen {d.get('failure_code')}: {d.get('failure_message') or 'no detail'}",
                            "actual_cost_cents": actual_cost_cents,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                    return
                final_url = d.get("video_url")
                if final_url:
                    actual_cost_cents += int(round(_estimate_duration_seconds(job["script"]) / 60.0 * 30.0))
                    await _finalize(job_id, ok=True, url=final_url, actual_cost_cents=actual_cost_cents)
                    return
            else:  # v2 polling
                s = await client.get(
                    f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                    headers={"X-Api-Key": heygen_key},
                )
                d = (s.json() or {}).get("data") or {}
                if d.get("status") == "completed":
                    actual_cost_cents += int(round(_estimate_duration_seconds(job["script"]) / 60.0 * 30.0))
                    final_url = d.get("video_url")
                    # Caption burn-in second pass — same fal.ai/auto-subtitle
                    # path the Faceless pipeline uses. We do it here (not in
                    # the HeyGen v3 payload) because HeyGen-side burn-in was
                    # inconsistent across avatars. Soft-fails: a caption
                    # outage never blocks the avatar render from shipping.
                    if final_url and job.get("captions"):
                        await db.renders.update_one(
                            {"id": job_id},
                            {"$set": {"progress": 92, "progress_label": "Burning in captions…"}},
                        )
                        try:
                            captioned = await _burn_in_captions(
                                final_url,
                                job.get("caption_style") or "boxed",
                                job.get("caption_position") or "bottom",
                            )
                            if captioned:
                                final_url = captioned
                                actual_cost_cents += CAPTION_BURN_COST_CENTS
                            else:
                                logger.warning(f"[captions] avatar job={job_id} burn-in returned no URL; shipping uncaptioned")
                        except Exception as exc:
                            logger.warning(f"[captions] avatar job={job_id} exception: {type(exc).__name__}: {exc}")
                    await _finalize(job_id, ok=True, url=final_url, actual_cost_cents=actual_cost_cents)
                    return
                if d.get("status") == "failed":
                    await db.renders.update_one(
                        {"id": job_id},
                        {"$set": {
                            "status": "failed",
                            "error": f"HeyGen returned status=failed: {d.get('error') or 'no detail'}",
                            "actual_cost_cents": actual_cost_cents,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                    return
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {
            "status": "failed",
            "error": "HeyGen polling timed out after 25 minutes",
            "actual_cost_cents": actual_cost_cents,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


# ---------------------------------------------------------------------------
# fal.ai Faceless pipeline — real renders only.
# Real flow: Kokoro TTS → Flux per-scene images → ffmpeg compose.
# ---------------------------------------------------------------------------
async def _run_render_faceless(job: dict):
    job_id = job["id"]
    scenes = job.get("scenes") or []
    actual_cost_cents = 0
    n_scenes = max(1, len(scenes))

    # ---- Stage 1/4: voiceover ----
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {"status": "voiceover", "progress": 10, "progress_label": "Preparing voiceover…"}},
    )
    await asyncio.sleep(0.8)

    # BYOK — Faceless pipeline: customer's fal.ai key takes precedence when
    # saved. Also flows into nested t2v / i2v / captions helpers via the
    # _override_fal_key contextvar (set once here, inherited by tasks).
    try:
        user_email = (job.get("user_email") or "").strip().lower()
        if user_email:
            user_fal = await get_byok_key(db, user_email, "fal")
            if user_fal:
                _override_fal_key_ctx.set(user_fal)
    except Exception as exc:
        logger.warning(f"[byok] faceless key lookup failed: {type(exc).__name__}: {exc}")
    fal_key = _effective_fal_key()

    if not fal_key:
        await _finalize(job_id, ok=False, url=None, actual_cost_cents=0)
        return

    fal_headers = {"Authorization": f"Key {fal_key}", "Content-Type": "application/json"}

    async def _set_progress(progress: int, label: str, status: Optional[str] = None):
        update = {"progress": progress, "progress_label": label}
        if status:
            update["status"] = status
        await db.renders.update_one({"id": job_id}, {"$set": update})

    async def _fal_queue_run(model_id: str, payload: dict, *, max_wait_s: int = 600) -> Optional[dict]:
        """Submit a job to fal.ai's queue endpoint and poll for completion."""
        async with httpx.AsyncClient(timeout=30) as qclient:
            sub = await qclient.post(f"https://queue.fal.run/{model_id}", headers=fal_headers, json=payload)
            if sub.status_code not in (200, 202):
                logger.warning(f"[fal-queue] {job_id} {model_id} submit FAIL {sub.status_code} {sub.text[:200]}")
                await db.renders.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "error": f"Compose submit error {sub.status_code}: {sub.text[:300]}",
                        "actual_cost_cents": actual_cost_cents,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return None
            sub_body = sub.json()
            req_id = sub_body.get("request_id")
            # fal.ai's queue uses the APP namespace (e.g. "fal-ai/ffmpeg-api"),
            # NOT the endpoint (e.g. "fal-ai/ffmpeg-api/compose"), for status
            # and result fetching. Always trust the URLs returned by the
            # submit response — constructing them from model_id breaks for any
            # endpoint with a sub-path (compose, wizper subtypes, etc.).
            status_url = sub_body.get("status_url")
            result_url = sub_body.get("response_url")
            if not req_id or not status_url or not result_url:
                await db.renders.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "error": f"Compose submit malformed (missing request_id/urls): {str(sub_body)[:300]}",
                        "actual_cost_cents": actual_cost_cents,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return None
            deadline = asyncio.get_event_loop().time() + max_wait_s
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(2)  # was 3s — snappier completion detection
                stat = await qclient.get(status_url, headers=fal_headers)
                if stat.status_code != 200:
                    continue
                st = stat.json().get("status", "")
                if st == "COMPLETED":
                    res = await qclient.get(result_url, headers=fal_headers)
                    if res.status_code != 200:
                        await db.renders.update_one(
                            {"id": job_id},
                            {"$set": {
                                "status": "failed",
                                "error": f"Compose fetch error {res.status_code}: {res.text[:300]}",
                                "actual_cost_cents": actual_cost_cents,
                                "completed_at": datetime.now(timezone.utc).isoformat(),
                            }},
                        )
                        return None
                    return res.json()
                if st == "FAILED":
                    err = stat.json()
                    await db.renders.update_one(
                        {"id": job_id},
                        {"$set": {
                            "status": "failed",
                            "error": f"Compose returned FAILED: {str(err)[:300]}",
                            "actual_cost_cents": actual_cost_cents,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                    return None
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {
                    "status": "failed",
                    "error": f"Compose polling timed out after {max_wait_s}s",
                    "actual_cost_cents": actual_cost_cents,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return None

    # 1) Kokoro TTS — fire as background task so Flux/T2V/stock work happens
    # in parallel with the voiceover. We only need the audio_url when we
    # compute per-scene durations (~50 lines below), so blocking here was
    # pure waste: the visuals phase doesn't need the audio at all. This
    # single restructure saves ~10-15s off every Faceless render.
    #
    # If the user uploaded a recorded voiceover, skip Kokoro entirely and
    # use the uploaded audio URL as the audio track. Render pipeline still
    # uses the same downstream path; only the source changes.
    user_voiceover_url = job.get("user_voiceover_url")
    await _set_progress(20, "Generating voiceover + visuals…" if not user_voiceover_url else "Preparing your voiceover + visuals…")
    # Bumped to 360s read timeout: long scripts (1000+ words) take Kokoro
    # 90-180s. The previous 120s cap was the root cause of "Voiceover error:
    # ReadError:" on multi-paragraph scripts. We also retry up to 2 times on
    # network reads inside `_run_tts` below.
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=360.0, write=60.0, pool=15.0)) as client:
        async def _run_tts():
            if user_voiceover_url:
                # No API call needed — the URL points to a file we already
                # have stored. Return a synthetic response object whose
                # JSON shape matches Kokoro's (so the downstream parser
                # doesn't need to branch).
                class _Resp:
                    status_code = 200
                    text = ""
                    def json(self):
                        return {"audio_url": user_voiceover_url}
                return _Resp()
            # 2 retries with backoff for transient ReadErrors. fal.run can
            # randomly close long reads when their upstream pod recycles;
            # the request is idempotent so retry is safe.
            last_exc: Optional[Exception] = None
            for attempt in range(3):
                try:
                    return await client.post(
                        f"https://fal.run/{_kokoro_endpoint(job.get('tts_voice_id') or 'af_heart')}",
                        headers=fal_headers,
                        json={"prompt": job["script"], "voice": job.get("tts_voice_id") or "af_heart"},
                    )
                except (httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                    last_exc = exc
                    if attempt < 2:
                        logger.warning(f"[tts] kokoro {type(exc).__name__} attempt {attempt+1}/3 — retrying")
                        await asyncio.sleep(2 + attempt * 2)
                        continue
                    raise
            if last_exc:
                raise last_exc
            return None  # unreachable but keeps the type checker happy

        tts_task = asyncio.create_task(_run_tts())

        # 2) Per-scene visuals. AI scenes use Flux 1.1 Pro; stock scenes use
        # their pre-picked URL. We surface per-scene progress so the user
        # knows exactly which scene is rendering.
        await _set_progress(30, f"Generating scene visuals (0 of {n_scenes})…", status="visuals")
        image_urls: list = [None] * len(scenes)

        async def gen_image(idx: int, prompt: str):
            # Content-hash cache: identical (prompt, aspect) renders return
            # the previously-generated Flux URL instantly. Re-renders with
            # the same script/aspect become near-instant — Flux dominates
            # the visuals phase, so this saves 20-60s on regen flows.
            import hashlib  # noqa: PLC0415
            aspect_tag = "p" if job["aspect"] == "9_16" else "l"
            cache_key = "flux:" + hashlib.sha256(
                f"{aspect_tag}|{prompt}".encode("utf-8")
            ).hexdigest()[:32]
            cached = await db.flux_cache.find_one({"_id": cache_key})
            if cached and cached.get("url"):
                return cached["url"]
            ir = await client.post(
                "https://fal.run/fal-ai/flux-pro/v1.1",
                headers=fal_headers,
                json={
                    # Hardened prompt: anchors the cinematic style + forbids
                    # the failure modes Charity flagged on 2026-02-23 — non-
                    # English garbled signage, blurry/AI-generated giveaways.
                    # `enable_safety_checker` stays default. `output_format`
                    # PNG ensures we get crisp downstream feed-into-Kling.
                    "prompt": (
                        f"{prompt}. Cinematic photograph, 8k, sharp focus, "
                        f"professional lighting, photorealistic, ultra detailed. "
                        f"No visible text or signage — if any text appears it "
                        f"must be clear, legible, perfectly spelled English only."
                    ),
                    "image_size": "portrait_16_9" if job["aspect"] == "9_16" else "landscape_16_9",
                    "num_inference_steps": 32,         # vs default 28 — sharper outputs
                    "guidance_scale": 4.0,             # tighter prompt adherence
                    "output_format": "png",
                },
            )
            if ir.status_code != 200:
                return None
            data = ir.json()
            url = (data.get("images") or [{}])[0].get("url")
            if url:
                # Write-through cache. fal.ai image URLs are signed with a
                # 7-day TTL — record `expires_at` so a future sweep can
                # purge stale entries. For now, every cache hit on a
                # purged URL falls back gracefully (compose just 404s on
                # that scene; downstream stitcher already handles missing
                # frames).
                await db.flux_cache.update_one(
                    {"_id": cache_key},
                    {"$set": {
                        "url": url,
                        "prompt": prompt,
                        "aspect": job["aspect"],
                        "cached_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
            return url

        # Resolve URLs per scene.
        #   - AI scenes  → Flux 1.1 Pro (still image; we ken-burns it later)
        #                   OR Kling/Veo/Pika text-to-video (when job.ai_engine
        #                   != "flux"). T2V scenes skip Flux entirely; the
        #                   prompt is generated into a real video in the
        #                   normalize step (where we know the per-scene
        #                   duration).
        #   - Stock scenes (pexels / pixabay / mix) → use pre-picked clip if
        #     present; otherwise auto-search the source and take the top hit.
        global_source = job.get("broll_source") or "ai"
        ai_engine = (job.get("ai_engine") or "flux").lower()
        is_t2v = ai_engine in T2V_ENGINES
        ai_tasks: list = []          # (idx, prompt) — Flux text-to-image jobs (engine="flux" only)
        stock_search_tasks: list = []  # (idx, source, query, orientation) — auto-search jobs
        scene_kind: list = ["" for _ in scenes]  # "ai" | "ai_t2v" | "stock"
        scene_prompts: list = ["" for _ in scenes]  # prompt text, used by ai_t2v + Flux-i2v scenes

        orientation = "portrait" if job["aspect"] == "9_16" else "landscape"
        for i, s in enumerate(scenes):
            effective_src = s.get("source") or global_source
            if effective_src == "ai":
                if is_t2v:
                    scene_kind[i] = "ai_t2v"
                    scene_prompts[i] = s.get("prompt") or ""
                    # Sentinel — we have a "resolved" scene (prompt is ready);
                    # the actual video is generated in normalize_scene.
                    image_urls[i] = "__t2v_pending__"
                else:
                    scene_kind[i] = "ai"
                    scene_prompts[i] = s.get("prompt") or ""  # needed by Kling i2v in normalize step
                    ai_tasks.append((i, s.get("prompt", "")))
            else:
                scene_kind[i] = "stock"
                pre_picked = s.get("video_url") or s.get("url")
                if pre_picked:
                    image_urls[i] = pre_picked
                else:
                    # No pre-picked clip — auto-search.
                    stock_search_tasks.append((i, effective_src, s.get("prompt") or "", orientation))

        completed = 0
        total_ai = len(ai_tasks)
        async def gen_and_tick(idx: int, prompt: str):
            nonlocal completed
            url = await gen_image(idx, prompt)
            image_urls[idx] = url
            completed += 1
            base = 30
            span = 20  # 30 → 50%
            pct = base + int(span * (completed / max(1, total_ai)))
            await _set_progress(pct, f"Generating scene visuals ({completed} of {n_scenes})…")
            return url

        # Fire Flux + auto-stock-search in parallel — independent network calls.
        async def auto_stock(idx: int, src: str, q: str, orient: str):
            url = await _auto_search_stock_url(src, q, orient)
            image_urls[idx] = url
            return url

        parallel_jobs = []
        if ai_tasks:
            parallel_jobs.extend([gen_and_tick(i, p) for i, p in ai_tasks])
        if stock_search_tasks:
            parallel_jobs.extend([auto_stock(i, src, q, o) for i, src, q, o in stock_search_tasks])
        if parallel_jobs:
            await asyncio.gather(*parallel_jobs)
            actual_cost_cents += total_ai * 4
            # Default Flux now upgrades to Kling i2v in the normalize step
            # for real AI motion. `flux_static` opts out and keeps the cheap
            # ken-burns path (no extra cost). 5s bucket dominates the spend.
            if ai_engine != "flux_static":
                actual_cost_cents += total_ai * KLING_I2V_COST_CENTS_5S
        # T2V scenes also accumulate cost — one premium clip per scene at the
        # engine's per-clip rate. Tracked separately so admin telemetry shows
        # the real spend per engine.
        if is_t2v:
            n_t2v = sum(1 for k in scene_kind if k == "ai_t2v")
            actual_cost_cents += n_t2v * T2V_ENGINES[ai_engine]["cost_cents"]

        # --- 3a) Await TTS BEFORE the httpx.AsyncClient context exits. ---
        # The `_run_tts` closure captures `client` from this `async with`
        # block; if we await it after the block exits, an in-flight Kokoro
        # POST (or a retry kicked off by ReadError) would call .post() on a
        # closed client and surface as "RuntimeError: Cannot send a request,
        # as the client has been closed." That was the exact failure Charity
        # hit on long-script Faceless renders on 2026-02-23. We capture the
        # parsed JSON here while the client is still alive, then continue
        # with all downstream work outside the block (the rest of the
        # pipeline doesn't touch `client`).
        try:
            tts_r = await tts_task
        except Exception as exc:  # noqa: BLE001
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {
                    "status": "failed",
                    "error": f"Voiceover error: {type(exc).__name__}: {exc}",
                    "actual_cost_cents": actual_cost_cents,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return
        if tts_r.status_code != 200:
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {
                    "status": "failed",
                    "error": f"Voiceover error {tts_r.status_code}: {tts_r.text[:300]}",
                    "actual_cost_cents": actual_cost_cents,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return
        tts_json = tts_r.json()

    # --- 3b) Audio duration — probe the real WAV file so video length matches
    # exactly. Falls back to the script-char estimate on probe failure. The
    # TTS response was already captured above while the httpx client was
    # alive; this block runs outside the async-with by design (it only
    # needs the parsed JSON + an independent _probe_audio_duration_s call
    # which manages its own client). ---
    audio_url = tts_json.get("audio_url") or (tts_json.get("audio") or {}).get("url")
    actual_cost_cents += int((len(job["script"]) / 1000.0) * 5)

    script_est_s = _estimate_duration_seconds(job["script"])
    audio_dur_s = await _probe_audio_duration_s(audio_url, script_est_s) if audio_url else script_est_s
    audio_dur_ms = max(3000, int(round(audio_dur_s * 1000)))

    # Drop scenes whose URL never resolved (Flux failed, stock search empty).
    surviving = [(i, image_urls[i]) for i in range(len(scenes)) if image_urls[i]]
    if not surviving:
        await db.renders.update_one(
            {"id": job_id},
            {"$set": {
                "status": "failed",
                "error": "Could not resolve any scene visuals (Flux/stock both empty).",
                "actual_cost_cents": actual_cost_cents,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return

    # Per-scene duration: distribute audio length proportional to each scene's
    # `weight` (= word count of the script sentence the scene visually covers).
    # That way cuts land on natural voiceover pauses instead of mid-sentence.
    # Falls back to equal split if the request has no weights (older client,
    # or the user manually edited scenes and dropped the auto-gen weights).
    n_surviving = len(surviving)
    raw_weights: list[int] = []
    for idx, _url in surviving:
        s = scenes[idx]
        try:
            w = int(s.get("weight") or 0)
        except (TypeError, ValueError):
            w = 0
        raw_weights.append(max(0, w))
    total_w = sum(raw_weights)
    if total_w <= 0:
        # No weights provided — equal split.
        per_dur_ms_list = [audio_dur_ms // n_surviving] * n_surviving
        per_dur_ms_list[-1] = audio_dur_ms - sum(per_dur_ms_list[:-1])
    else:
        per_dur_ms_list = []
        accum = 0
        for i, w in enumerate(raw_weights):
            if i == n_surviving - 1:
                per_dur_ms_list.append(audio_dur_ms - accum)
            else:
                slot = (audio_dur_ms * w) // total_w
                # Minimum 1.0s per scene so a single-word "beat" doesn't flash by.
                slot = max(1000, slot)
                per_dur_ms_list.append(slot)
                accum += slot
        # Sanity: durations must sum to audio_dur_ms — fix drift if any.
        diff = audio_dur_ms - sum(per_dur_ms_list)
        if diff != 0:
            per_dur_ms_list[-1] += diff

    # --- 4) Normalize ALL scenes to per-scene MP4s of the exact length.
    # AI Flux images → Ken Burns'd MP4. Stock clips → trimmed-and-scaled MP4.
    # We MUST pre-trim stock videos because fal.ai's ffmpeg-compose IGNORES the
    # keyframe `duration` for video keyframes and plays the source at native
    # length — that's why earlier 6-Pexels renders came out 115 seconds long
    # for a 16-second voiceover. ---
    await _set_progress(55, "Adding motion to scenes…")

    async def normalize_scene(slot: int, idx: int, url: str):
        this_dur = per_dur_ms_list[slot]
        kind = scene_kind[idx]
        if kind == "ai":
            # `flux_static` is the explicit opt-out: stills + cheap ken-burns
            # (no Kling i2v cost). Default `flux` upgrades to real AI motion
            # via Kling 2.1 standard. Falls back to ken-burns if Kling fails.
            if ai_engine == "flux_static":
                mp4 = await _make_kenburns_mp4(url, job["aspect"], this_dur, idx)
            else:
                mp4 = await _make_i2v_clip(
                    url, scene_prompts[idx], job["aspect"], this_dur, idx,
                )
                if not mp4:
                    logger.warning(f"[i2v] scene {idx} Kling failed — falling back to ken-burns")
                    mp4 = await _make_kenburns_mp4(url, job["aspect"], this_dur, idx)
        elif kind == "ai_t2v":
            # url is the "__t2v_pending__" sentinel — generate the real video
            # via Kling/Veo/Pika using the stored prompt at this exact duration.
            mp4 = await _make_t2v_clip(
                scene_prompts[idx], job["aspect"], this_dur, ai_engine, idx,
            )
        else:
            mp4 = await _trim_stock_video(url, job["aspect"], this_dur, idx)
        if mp4:
            return (idx, mp4, "video", this_dur)
        # ffmpeg/upload failed — drop the scene so we keep the track uniform.
        return None

    raw_results = await asyncio.gather(*[
        normalize_scene(slot, idx, url) for slot, (idx, url) in enumerate(surviving)
    ])
    kburns_results = [r for r in raw_results if r is not None]
    if not kburns_results:
        await db.renders.update_one(
            {"id": job_id},
            {"$set": {
                "status": "failed",
                "error": "Could not prepare any scene (ffmpeg/upload all failed). Try again.",
                "actual_cost_cents": actual_cost_cents,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return
    n_surviving = len(kburns_results)

    await _set_progress(70, f"Stitching {n_surviving} scenes…", status="composing")

    # --- 5) Build compose payload. fal.ai's ffmpeg-compose allows AT MOST one
    # video track. Every scene is now a video (stock MP4 or ken-burns'd Flux
    # image), so they all live in a single video track as sequential keyframes.
    # `timestamp` + `duration` are in MILLISECONDS per the schema. Per-scene
    # duration is whatever the normalize step actually produced — which itself
    # tracks the weighted-by-script-beat allocation computed earlier. ---
    visual_keyframes: list = []
    cursor_ms = 0
    for slot, (_idx, url, _kind, this_dur) in enumerate(kburns_results):
        visual_keyframes.append({"url": url, "timestamp": cursor_ms, "duration": this_dur})
        cursor_ms += this_dur

    total_video_ms = cursor_ms
    tracks: list = [{"id": "visuals", "type": "video", "keyframes": visual_keyframes}]
    if audio_url:
        tracks.append({
            "id": "audio",
            "type": "audio",
            "keyframes": [{"url": audio_url, "timestamp": 0, "duration": total_video_ms}],
        })

    # Background ticker so progress feels alive while fal compose works.
    stop_ticking = asyncio.Event()

    async def tick_compose_progress():
        scene_idx = 1
        progress_pct = 70
        while not stop_ticking.is_set():
            try:
                await asyncio.wait_for(stop_ticking.wait(), timeout=4.0)
                break
            except asyncio.TimeoutError:
                pass
            scene_idx = min(n_surviving, scene_idx + 1)
            progress_pct = min(90, progress_pct + 2)
            try:
                await _set_progress(progress_pct, f"Stitching scene {scene_idx} of {n_surviving}…")
            except Exception:
                pass

    ticker_task = asyncio.create_task(tick_compose_progress())
    try:
        compose_res = await _fal_queue_run(
            "fal-ai/ffmpeg-api/compose",
            {"tracks": tracks},
            max_wait_s=900,
        )
    finally:
        stop_ticking.set()
        try:
            await asyncio.wait_for(ticker_task, timeout=1.0)
        except Exception:
            pass

    actual_cost_cents += 2
    if not compose_res:
        return  # _fal_queue_run already finalized the job with an error
    composed_url = compose_res.get("video_url") or (compose_res.get("video") or {}).get("url")

    # --- Caption burn-in (second compose pass) ---------------------------
    # User-uploaded voiceovers + Kokoro TTS both produce clean audio that
    # transcribes well, so we can run the auto-subtitle pass even when the
    # voice source is the user's recording. Auto-subtitle transcribes the
    # audio fresh and burns word-level highlighted captions onto the video.
    # Style maps `caption_style` ("boxed" | "tiktok" | "minimal") to a
    # concrete preset of font/colour/position/words-per-segment.
    if composed_url and job.get("captions"):
        try:
            await _set_progress(92, "Burning in captions…")
            captioned_url = await _burn_in_captions(
                composed_url,
                job.get("caption_style") or "boxed",
                job.get("caption_position") or "bottom",
            )
            if captioned_url:
                composed_url = captioned_url
                # Auto-subtitle pricing on fal.ai is ~$0.10 per video.
                actual_cost_cents += CAPTION_BURN_COST_CENTS
            else:
                # Soft-fail: ship the no-caption render rather than blocking.
                logger.warning(f"[captions] burn-in returned no URL for job={job_id}; shipping uncaptioned")
        except Exception as exc:
            logger.warning(f"[captions] burn-in exception for job={job_id}: {type(exc).__name__}: {exc}")

    await _finalize(job_id, ok=True, url=composed_url, actual_cost_cents=actual_cost_cents)


# ---------------------------------------------------------------------------
# Composite Avatar + B-roll cutaways pipeline — real renders only.
# Real flow: render HeyGen talking-head as base track + Flux B-roll cutaways
# every N seconds + ffmpeg overlay.
# ---------------------------------------------------------------------------
async def _run_render_composite(job: dict):
    job_id = job["id"]
    duration_s = _estimate_duration_seconds(job["script"])
    interval_s = max(1, int(job.get("broll_cutaway_interval_s", 12)))
    cutaway_count = max(1, int(duration_s / interval_s))

    await _walk_stages(job_id, [
        ("avatar", 25, "Generating avatar video…"),
        ("cutaways", 55, f"Generating {cutaway_count} b-roll cutaways…"),
        ("composing", 85, "Composing final video…"),
    ])

    # Real path: render HeyGen talking-head as base track, generate
    # cutaway_count Flux B-roll images, then call ffmpeg overlay endpoint
    # with cutaway timestamps. Not yet implemented — surface a clear error.
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {
            "status": "failed",
            "error": "Composite render not implemented yet. Use Avatar or Faceless mode for now.",
            "actual_cost_cents": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


@api.post("/studio/render/estimate")
async def studio_render_estimate(payload: RenderRequest, user: AuthUser = Depends(current_user)):
    """Internal telemetry: conservative cost estimate (cents) for a candidate
    render. No customer-facing cap enforcement — the silent circuit-breaker
    lives in /studio/render and uses RENDER_COST_CIRCUIT_BREAKER_CENTS."""
    require_studio(user)
    cents = estimate_render_cost_cents(payload)
    return {
        "estimated_cost_cents": cents,
        "estimated_cost_dollars": round(cents / 100.0, 2),
    }


@api.post("/studio/render")
async def studio_render(payload: RenderRequest, user: AuthUser = Depends(current_user)):
    require_studio(user)
    if payload.mode not in ("avatar", "faceless", "composite"):
        raise HTTPException(status_code=400, detail="Bad mode")
    if not payload.script.strip():
        raise HTTPException(status_code=400, detail="Script required")

    # Silent runaway-cost circuit-breaker. Not customer-facing cost
    # protection — exists to catch pathological inputs (malformed scripts,
    # scene counts, etc.) before they hit a paid API. Plan-level usage
    # caps live at the subscription layer (not enforced in code yet).
    estimated_cents = estimate_render_cost_cents(payload)
    if estimated_cents > RENDER_COST_CIRCUIT_BREAKER_CENTS:
        logging.warning(
            "Render circuit-breaker tripped: user=%s mode=%s estimated=%s¢ threshold=%s¢ script_len=%s scenes=%s",
            user.email, payload.mode, estimated_cents, RENDER_COST_CIRCUIT_BREAKER_CENTS,
            len(payload.script), len(payload.scenes),
        )
        raise HTTPException(
            status_code=400,
            detail="Render configuration is too large. Please contact support.",
        )

    # Group B quota gate — atomically check + decrement the buyer's monthly
    # render allowance before we kick off the background pipeline. Founders
    # and dev_bypass admins are passed through unconditionally. Returns the
    # snapshot of the buyer doc post-decrement so we can pass it to the
    # background runner (used to refund the slot if the render fails).
    quota_snapshot = await _quota_gate_or_402(
        email=user.email,
        mode=payload.mode,
        estimated_cents=estimated_cents,
    )

    job_id = str(uuid.uuid4())
    doc = {
        "id": job_id,
        "user_email": user.email,
        "mode": payload.mode,
        "aspect": payload.aspect,
        "captions": payload.captions,
        "script": payload.script,
        "avatar_id": payload.avatar_id,
        "voice_id": payload.voice_id,
        "tts_voice_id": payload.tts_voice_id,
        "broll_source": payload.broll_source,
        "scenes": payload.scenes,
        "ai_engine": payload.ai_engine,
        "broll_cutaway_interval_s": payload.broll_cutaway_interval_s,
        "caption_style": payload.caption_style,
        "caption_position": payload.caption_position,
        # User-uploaded voiceover URL — when set, the faceless pipeline
        # skips Kokoro TTS entirely and uses this audio as the voiceover.
        # See _run_render_faceless line ~1771 for the override branch.
        "user_voiceover_url": payload.user_voiceover_url,
        "status": "queued",
        "progress": 5,
        "progress_label": "Queued…",
        "result_url": None,
        "error": None,
        "estimated_cost_cents": estimated_cents,
        "actual_cost_cents": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    await db.renders.insert_one(doc)
    await _log_activity("studio_render", user.email, {
        "job_id": job_id,
        "mode": payload.mode,
        "aspect": payload.aspect,
        "captions": payload.captions,
        "avatar_id": payload.avatar_id,
        "voice_id": payload.voice_id,
        "tts_voice_id": payload.tts_voice_id,
        "broll_source": payload.broll_source,
        "scene_count": len(payload.scenes),
        "estimated_cost_cents": estimated_cents,
    })

    # Kick off background work
    asyncio.create_task(_run_render(job_id))

    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Quota gate (Group B of the AppSumo launch plan)
# ---------------------------------------------------------------------------
# Atomic per-render check + decrement against the buyer's anniversary cycle.
# Three failure modes, all surfaced as 402 Payment Required with a structured
# body the frontend uses to render the friendly "You've used all X renders
# this cycle. Resets in N days · upgrade →" prompt:
#
#   • render_quota_exhausted — buyer hit their total render cap
#   • avatar_sub_cap_exhausted — buyer still has render budget but hit the
#     tier's Avatar sub-cap (protects HeyGen spend on T3/T4)
#   • cost_cap_exhausted — buyer's monthlyCostCents + estimate would breach
#     the per-tier kill-switch ceiling. Same friendly copy on the wire (the
#     differentiation lives only in the Activity log so admin can see why).
#
# Founders bypass all three checks. Dev_bypass and STUDIO_GRANT admins are
# implicit founders for gating purposes — they should never be rate-limited
# while developing/supporting the app.
#
# The check + decrement is atomic via $expr-conditioned findOneAndUpdate so
# concurrent renders from the same user can't race past the cap.
# ---------------------------------------------------------------------------
async def _quota_gate_or_402(*, email: str, mode: str, estimated_cents: int) -> dict | None:
    """Returns the post-decrement buyer snapshot when the render is allowed,
    or raises HTTPException(402) with a frontend-friendly body otherwise.
    Returns None for founders/dev/grant users so the caller knows to skip
    the refund-on-failure path."""

    # Dev bypass + STUDIO_GRANT_EMAILS skip the gate entirely. They aren't
    # necessarily in db.buyers, and we never want our own owner email to
    # get rate-limited while building/supporting the app.
    if DEV_BYPASS_EMAIL and email == DEV_BYPASS_EMAIL:
        return None
    if email in STUDIO_GRANT_EMAILS:
        return None

    buyer = await db.buyers.find_one({"email": email})
    if not buyer:
        # No buyer record means /auth/check would have already rejected this
        # request. If we still got here, treat it as a forbidden path rather
        # than a quota issue — better signal for monitoring.
        raise HTTPException(status_code=403, detail="Buyer record missing")
    if buyer.get("founders"):
        return None

    # Tier-aware caps. For pre-migration buyers without a `tier` field yet,
    # fall back to deriving from entitlements (same logic admin Usage uses).
    from tier_config import get_tier, tier_for_entitlements
    tier_id = (buyer.get("tier") or "").strip().lower()
    if not tier_id:
        tier_id = tier_for_entitlements(list(buyer.get("entitlements") or [])).id
    tier = get_tier(tier_id)

    used_total  = int(buyer.get("rendersThisCycle") or 0)
    used_avatar = int(buyer.get("avatarRendersThisCycle") or 0)
    cost_so_far = int(buyer.get("monthlyCostCents") or 0)
    cost_cap    = int(buyer.get("monthlyCostCapCents") or tier.monthly_cost_cap_cents)
    quota_total = int(buyer.get("renderQuotaMonthly") or tier.render_quota_monthly)
    avatar_cap  = int(buyer.get("avatarSubCap") or tier.avatar_sub_cap)
    cycle_ends  = buyer.get("cycleResetsAt")

    # All three failure modes share a single 402 message so the user sees
    # "You've used your renders, here's when more are available" regardless
    # of WHY internally — keeps cost-cap math invisible. Admin can see the
    # actual reason in the Activity log.
    def _exhausted(reason: str, used: int, total: int) -> HTTPException:
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
        from tier_config import TIERS_ORDERED
        ordered_ids = [t.id for t in TIERS_ORDERED]
        upgrade_to = None
        try:
            cur_idx = ordered_ids.index(tier_id)
            if cur_idx < len(ordered_ids) - 1:
                upgrade_to = TIERS_ORDERED[cur_idx + 1]
        except ValueError:
            pass
        upgrade_msg = (
            f" Upgrade to {upgrade_to.label} for {upgrade_to.render_quota_monthly} renders/month →"
            if upgrade_to else ""
        )
        return HTTPException(
            status_code=402,
            detail={
                "reason": reason,
                "message": f"You've used all {total} renders this cycle.{days_left}{upgrade_msg}",
                "quota_used": used,
                "quota_total": total,
                "cycle_resets_at": cycle_ends,
                "tier": tier_id,
                "upgrade_to": upgrade_to.id if upgrade_to else None,
            },
        )

    # Defensive: tier with zero renders allowed is a misset; reject cleanly.
    if quota_total <= 0:
        await _log_activity("quota_blocked", email, {
            "reason": "render_quota_zero", "tier": tier_id,
        })
        raise _exhausted("render_quota_exhausted", 0, 0)

    # Check 1 — total render cap.
    if used_total >= quota_total:
        await _log_activity("quota_blocked", email, {
            "reason": "render_quota_exhausted",
            "tier": tier_id, "used": used_total, "total": quota_total,
        })
        raise _exhausted("render_quota_exhausted", used_total, quota_total)

    # Check 2 — avatar sub-cap (only if user is attempting an avatar render).
    if mode == "avatar" and used_avatar >= avatar_cap:
        await _log_activity("quota_blocked", email, {
            "reason": "avatar_sub_cap_exhausted",
            "tier": tier_id, "used": used_avatar, "total": avatar_cap,
        })
        raise _exhausted("avatar_sub_cap_exhausted", used_avatar, avatar_cap)

    # Check 3 — silent cost-cap kill-switch. Same friendly copy on the wire
    # so customers don't see "you hit your monthly cost ceiling" — they see
    # the standard quota-exhausted message and the internal reason hides in
    # the activity log for admin visibility.
    if cost_cap > 0 and (cost_so_far + estimated_cents) > cost_cap:
        await _log_activity("quota_blocked", email, {
            "reason": "cost_cap_exhausted",
            "tier": tier_id, "cost_so_far": cost_so_far,
            "estimated_cents": estimated_cents, "cap_cents": cost_cap,
        })
        raise _exhausted("cost_cap_exhausted", used_total, quota_total)

    # Atomic decrement. The $expr clause guards against races where two
    # concurrent renders both pass the pre-check above — only one will
    # satisfy the condition and win the slot. Mongo's findOneAndUpdate is
    # atomic at the document level, which is exactly what we need here.
    avatar_inc = 1 if mode == "avatar" else 0
    expr_clauses = [
        {"$lt": [{"$ifNull": ["$rendersThisCycle", 0]}, quota_total]},
    ]
    if mode == "avatar":
        expr_clauses.append(
            {"$lt": [{"$ifNull": ["$avatarRendersThisCycle", 0]}, avatar_cap]},
        )
    updated = await db.buyers.find_one_and_update(
        {"email": email, "$expr": {"$and": expr_clauses}},
        {"$inc": {
            "rendersThisCycle": 1,
            "avatarRendersThisCycle": avatar_inc,
            "monthlyCostCents": estimated_cents,
        }},
        return_document=True,
    )
    if not updated:
        await _log_activity("quota_blocked", email, {
            "reason": "race_lost", "tier": tier_id,
        })
        raise _exhausted("render_quota_exhausted", used_total, quota_total)
    return updated


async def _refund_quota_slot(*, email: str, mode: str, estimated_cents: int) -> None:
    """Reverse a successful quota gate when a render fails. Mirrors the
    gate's $inc but with negative values. Skipped for founders / dev /
    STUDIO_GRANT (they never decremented in the first place — signaled by
    the gate returning None instead of a buyer snapshot).
    """
    if DEV_BYPASS_EMAIL and email == DEV_BYPASS_EMAIL:
        return
    if email in STUDIO_GRANT_EMAILS:
        return
    avatar_dec = -1 if mode == "avatar" else 0
    try:
        await db.buyers.update_one(
            {"email": email, "founders": {"$ne": True}},
            {"$inc": {
                "rendersThisCycle": -1,
                "avatarRendersThisCycle": avatar_dec,
                "monthlyCostCents": -estimated_cents,
            }},
        )
    except Exception as exc:
        logger.warning(f"[quota] refund failed for {email}: {type(exc).__name__}: {exc}")



@api.post("/studio/render/both-aspects")
async def studio_render_both_aspects(payload: RenderRequest, user: AuthUser = Depends(current_user)):
    """Fire TWO renders in parallel — one in 9:16 and one in 16:9 — using the
    same script, avatar/voice, scenes, and AI engine. Returns both job docs
    so the frontend can track them independently. Saves the user from
    manually queueing the same render twice with the aspect toggle flipped."""
    require_studio(user)
    if payload.mode not in ("avatar", "faceless", "composite"):
        raise HTTPException(status_code=400, detail="Bad mode")
    if not payload.script.strip():
        raise HTTPException(status_code=400, detail="Script required")

    jobs = []
    # Track which aspects already passed the quota gate so we can refund
    # if the SECOND gate-call raises (e.g. user has 1 render left + clicks
    # both-aspects → first call consumes it, second call must 402 cleanly
    # AND refund the first slot we just took).
    gated_aspects: list[tuple[str, int]] = []  # (mode, estimated_cents)
    for aspect in ("9_16", "16_9"):
        per_payload = payload.model_copy(update={"aspect": aspect})
        estimated_cents = estimate_render_cost_cents(per_payload)
        if estimated_cents > RENDER_COST_CIRCUIT_BREAKER_CENTS:
            logging.warning(
                "Both-aspects render circuit-breaker tripped: user=%s aspect=%s estimated=%s¢ threshold=%s¢",
                user.email, aspect, estimated_cents, RENDER_COST_CIRCUIT_BREAKER_CENTS,
            )
            # Refund any already-consumed slot before bailing.
            for prev_mode, prev_cents in gated_aspects:
                await _refund_quota_slot(email=user.email, mode=prev_mode, estimated_cents=prev_cents)
            raise HTTPException(
                status_code=400,
                detail="Render configuration is too large. Please contact support.",
            )

        # Group B quota gate per render. Both-aspects fires two renders, so
        # we consume two slots — one per aspect. If the second gate-call
        # raises, refund the first slot we already took so the user isn't
        # silently charged a quota slot for an unrun render.
        try:
            await _quota_gate_or_402(
                email=user.email,
                mode=per_payload.mode,
                estimated_cents=estimated_cents,
            )
        except HTTPException:
            for prev_mode, prev_cents in gated_aspects:
                await _refund_quota_slot(email=user.email, mode=prev_mode, estimated_cents=prev_cents)
            raise
        gated_aspects.append((per_payload.mode, estimated_cents))

        job_id = str(uuid.uuid4())
        doc = {
            "id": job_id,
            "user_email": user.email,
            "mode": per_payload.mode,
            "aspect": per_payload.aspect,
            "captions": per_payload.captions,
            "script": per_payload.script,
            "avatar_id": per_payload.avatar_id,
            "voice_id": per_payload.voice_id,
            "tts_voice_id": per_payload.tts_voice_id,
            "broll_source": per_payload.broll_source,
            "scenes": per_payload.scenes,
            "ai_engine": per_payload.ai_engine,
            "broll_cutaway_interval_s": per_payload.broll_cutaway_interval_s,
            "caption_style": per_payload.caption_style,
            "caption_position": per_payload.caption_position,
            "user_voiceover_url": per_payload.user_voiceover_url,
            "status": "queued",
            "progress": 5,
            "progress_label": "Queued…",
            "result_url": None,
            "error": None,
            "estimated_cost_cents": estimated_cents,
            "actual_cost_cents": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
        await db.renders.insert_one(doc)
        await _log_activity("studio_render", user.email, {
            "job_id": job_id,
            "mode": per_payload.mode,
            "aspect": aspect,
            "batch": "both-aspects",
            "scene_count": len(per_payload.scenes),
            "estimated_cost_cents": estimated_cents,
        })
        asyncio.create_task(_run_render(job_id))
        doc.pop("_id", None)
        jobs.append(doc)
    return {"jobs": jobs}


@api.get("/studio/render/{job_id}")
async def studio_render_status(job_id: str, user: AuthUser = Depends(current_user)):
    require_studio(user)
    doc = await db.renders.find_one({"id": job_id, "user_email": user.email})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc.pop("_id", None)
    return doc


@api.get("/studio/history")
async def studio_history(user: AuthUser = Depends(current_user)):
    require_studio(user)
    cursor = db.renders.find({"user_email": user.email}).sort("created_at", -1).limit(50)
    items = []
    async for doc in cursor:
        doc.pop("_id", None)
        items.append(doc)
    return {"items": items}


@api.delete("/studio/render/{job_id}")
async def studio_render_delete(job_id: str, user: AuthUser = Depends(current_user)):
    require_studio(user)
    doc = await db.renders.find_one({"id": job_id, "user_email": user.email})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    # Admins can force-delete any status (covers stuck-in-progress orphans).
    # Customers can only delete completed/failed renders so an active
    # background task doesn't write to a vanished doc.
    is_admin = user.is_admin
    if not is_admin and doc["status"] not in ("complete", "failed"):
        raise HTTPException(status_code=409, detail="In-progress renders cannot be deleted")
    await db.renders.delete_one({"id": job_id, "user_email": user.email})
    await _log_activity("studio_render_deleted", user.email, {
        "job_id": job_id,
        "force_admin": is_admin and doc["status"] not in ("complete", "failed"),
        "prior_status": doc["status"],
    })
    return {"ok": True}


class BulkDeleteRequest(BaseModel):
    ids: list[str]


@api.post("/studio/render/bulk-delete")
async def studio_render_bulk_delete(payload: BulkDeleteRequest, user: AuthUser = Depends(current_user)):
    """Delete multiple renders in one shot. Customers can only delete
    completed/failed renders so an active background task doesn't write to
    a vanished doc — admins can force-delete any status (covers stuck-in-
    progress orphans whose worker task already died)."""
    require_studio(user)
    if not payload.ids:
        return {"deleted": 0}
    q = {"id": {"$in": payload.ids}, "user_email": user.email}
    is_admin = user.is_admin
    if not is_admin:
        q["status"] = {"$in": ["complete", "failed"]}
    res = await db.renders.delete_many(q)
    await _log_activity("studio_render_bulk_deleted", user.email, {
        "requested": len(payload.ids),
        "deleted": res.deleted_count,
        "force_admin": is_admin,
    })
    return {"deleted": res.deleted_count}



# ---------------------------------------------------------------------------
# Script Engine — Claude via Emergent Universal LLM Key
# ---------------------------------------------------------------------------
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"


async def _anthropic_direct_complete(api_key: str, system_prompt: str, user_message: str) -> str:
    """BYOK path: hit Anthropic's Messages API directly with the customer's
    sk-ant-… key. Bypasses the Emergent universal LLM key entirely so the
    customer's own quota is consumed."""
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Anthropic error {r.status_code}: {r.text[:200]}")
    body = r.json()
    blocks = body.get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


async def _claude_complete(system_prompt: str, user_message: str, session_id: str | None = None, user_email: str | None = None) -> str:
    """Single-shot Claude completion. If the user has saved a BYOK Anthropic
    key, route directly to Anthropic; else use the Emergent universal LLM key."""
    # BYOK: customer's own Anthropic key takes precedence (consumes their quota).
    if user_email:
        try:
            anthropic_key = await get_byok_key(db, user_email, "anthropic")
            if anthropic_key:
                return await _anthropic_direct_complete(anthropic_key, system_prompt, user_message)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"[byok] anthropic single-shot lookup failed: {type(exc).__name__}: {exc}")

    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="LLM key missing")
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # lazy import
    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id or str(uuid.uuid4()),
            system_message=system_prompt,
        )
        .with_model("anthropic", CLAUDE_MODEL)
    )
    try:
        return await chat.send_message(UserMessage(text=user_message))
    except Exception as e:  # noqa: BLE001 — surface a clean 502 to the client
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")


# --- Studio helper: generate B-roll prompts from a script -------------------

class BrollPromptsRequest(BaseModel):
    script: str


@api.post("/studio/broll-prompts")
async def studio_broll_prompts(payload: BrollPromptsRequest, user: AuthUser = Depends(current_user)):
    require_studio(user)
    if not payload.script.strip():
        raise HTTPException(status_code=400, detail="Script required")

    # Split the script into natural beats FIRST so we get a deterministic
    # scene count + per-scene word weights. Claude only handles wording each
    # beat into a stock-friendly prompt — not deciding how many to generate.
    beats = split_script_into_beats(payload.script, min_beats=3, max_beats=12)
    if not beats:
        return {"prompts": [], "scenes": []}

    numbered = "\n".join(f"{i+1}. {text}" for i, (text, _) in enumerate(beats))
    user_msg = (
        f"Generate exactly {len(beats)} B-roll search prompts — one per beat below, in order. "
        f"The viewer sees prompt #N while beat #N is being spoken.\n\n"
        f"Beats:\n{numbered}"
    )
    text = await _claude_complete(BROLL_PROMPTS_SYSTEM, user_msg, user_email=user.email)

    # Parse: one per line, drop blanks, strip bullets/quotes/numbering
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("0123456789. -*•").strip().strip('"\u201c\u201d').strip()
        if line:
            out.append(line)

    # Pair prompts with beat weights (word counts). If Claude returned fewer
    # prompts than beats, fall back to the beat text itself for the missing
    # slots — better to ship a less-polished prompt than to drop a scene.
    scenes: list[dict] = []
    for i, (beat_text, weight) in enumerate(beats):
        prompt = out[i] if i < len(out) else beat_text[:60]
        scenes.append({"prompt": prompt, "weight": weight})

    return {
        "prompts": [s["prompt"] for s in scenes],
        "scenes": scenes,
    }


# --- Studio: 3-thumbnail-per-scene candidates ------------------------------
# Returns top 3 candidate stock clips per prompt so the user can preview and
# pick before kicking off a render. Massive UX win vs the current model where
# the auto-pick happens silently inside the render pipeline. Implemented as a
# single endpoint that fans out N prompts × 3 candidates with concurrent
# requests — Pexels/Pixabay handle this fine and the response is fast (~2s
# for 5 prompts).
class StockCandidatesRequest(BaseModel):
    prompts: list[str]
    source: str = "pexels"  # pexels | pixabay | mix
    orientation: str = "portrait"  # portrait | landscape


@api.post("/studio/stock-candidates")
async def studio_stock_candidates(
    payload: StockCandidatesRequest,
    user: AuthUser = Depends(current_user),
):
    require_studio(user)
    if not payload.prompts:
        return {"candidates": []}
    if payload.source not in ("pexels", "pixabay", "mix"):
        raise HTTPException(status_code=400, detail="Bad source")

    sources_for_prompt = ["pexels", "pixabay"] if payload.source == "mix" else [payload.source]

    async def fetch_one(idx: int, prompt: str) -> dict:
        query = _extract_stock_query(prompt) or prompt
        keyword_set = {w for w in query.split() if w}
        hits: list[dict] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for src in sources_for_prompt:
                try:
                    if src == "pexels" and PEXELS_API_KEY:
                        r = await client.get(
                            "https://api.pexels.com/videos/search",
                            headers={"Authorization": PEXELS_API_KEY},
                            params={"query": query, "orientation": payload.orientation, "per_page": 12},
                        )
                        if r.status_code != 200:
                            continue
                        cands = r.json().get("videos") or []
                        cands.sort(key=lambda v: _score_pexels_hit(v, keyword_set), reverse=True)
                        for v in cands[:5]:
                            files = v.get("video_files") or []
                            files.sort(key=lambda f: (f.get("height") or 0))
                            pick = next(
                                (f for f in files if 720 <= (f.get("height") or 0) <= 1080),
                                None,
                            )
                            if not pick and files:
                                higher = [f for f in files if (f.get("height") or 0) >= 720]
                                pick = higher[0] if higher else None
                            if pick and pick.get("link"):
                                hits.append({
                                    "id": f"pex-{v.get('id')}",
                                    "thumb": v.get("image"),
                                    "video_url": pick["link"],
                                    "duration": v.get("duration"),
                                    "source": "pexels",
                                })
                    elif src == "pixabay" and PIXABAY_API_KEY:
                        r = await client.get(
                            "https://pixabay.com/api/videos/",
                            params={
                                "key": PIXABAY_API_KEY, "q": query, "per_page": 12,
                                "order": "popular", "safesearch": "true",
                            },
                        )
                        if r.status_code != 200:
                            continue
                        cands = r.json().get("hits") or []
                        cands.sort(
                            key=lambda v: sum(1 for k in keyword_set if k in (v.get("tags") or "").lower()),
                            reverse=True,
                        )
                        for v in cands[:5]:
                            videos = v.get("videos") or {}
                            pick = videos.get("large") or videos.get("medium")
                            if pick and pick.get("url"):
                                hits.append({
                                    "id": f"pix-{v.get('id')}",
                                    "thumb": (pick.get("thumbnail")
                                              or (videos.get("medium") or {}).get("thumbnail")
                                              or (videos.get("small") or {}).get("thumbnail")),
                                    "video_url": pick["url"],
                                    "duration": v.get("duration"),
                                    "source": "pixabay",
                                })
                except Exception as exc:
                    logger.warning(f"[stock-candidates] {src}/{prompt}: {exc}")
                    continue
        return {"idx": idx, "prompt": prompt, "candidates": hits[:3]}

    results = await asyncio.gather(*[fetch_one(i, p) for i, p in enumerate(payload.prompts)])
    # Preserve original order
    results.sort(key=lambda r: r["idx"])
    return {"candidates": results}


# --- Studio: AI Flux previews per scene -----------------------------------
# Generates ONE Flux still per (prompt, aspect) so the user can see what each
# AI scene will look like BEFORE kicking off the render. Critical UX win —
# Charity flagged the "AI drawings are sometimes really bad" failure mode on
# 2026-02-23 and wanted to preview them inline.
#
# Implementation reuses the existing `db.flux_cache` so previews are FREE for
# the actual render — the cached URL is exactly what the renderer would have
# fetched anyway. Cost is $0.04/scene per uncached prompt, which is the same
# cost the user would pay at render time. No double-charge.
class AIPreviewsRequest(BaseModel):
    prompts: list[str]
    aspect: str = "9_16"


@api.post("/studio/ai-previews")
async def studio_ai_previews(payload: AIPreviewsRequest, user: AuthUser = Depends(current_user)):
    require_studio(user)
    if not payload.prompts:
        return {"previews": []}
    if payload.aspect not in ("9_16", "16_9"):
        raise HTTPException(status_code=400, detail="Bad aspect")
    if not FAL_API_KEY:
        raise HTTPException(status_code=503, detail="Image generation unavailable")
    fal_headers = {"Authorization": f"Key {FAL_API_KEY}"}
    aspect_tag = "p" if payload.aspect == "9_16" else "l"

    async def gen_one(idx: int, prompt: str) -> dict:
        # Same cache key shape as the render pipeline so previews = real frames.
        import hashlib  # noqa: PLC0415
        cache_key = "flux:" + hashlib.sha256(
            f"{aspect_tag}|{prompt}".encode("utf-8")
        ).hexdigest()[:32]
        cached = await db.flux_cache.find_one({"_id": cache_key})
        if cached and cached.get("url"):
            return {"idx": idx, "prompt": prompt, "image_url": cached["url"], "cached": True}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                ir = await client.post(
                    "https://fal.run/fal-ai/flux-pro/v1.1",
                    headers=fal_headers,
                    json={
                        "prompt": (
                            f"{prompt}. Cinematic photograph, 8k, sharp focus, "
                            f"professional lighting, photorealistic, ultra detailed. "
                            f"No visible text or signage — if any text appears it "
                            f"must be clear, legible, perfectly spelled English only."
                        ),
                        "image_size": "portrait_16_9" if payload.aspect == "9_16" else "landscape_16_9",
                        "num_inference_steps": 32,
                        "guidance_scale": 4.0,
                        "output_format": "png",
                    },
                )
                if ir.status_code != 200:
                    return {"idx": idx, "prompt": prompt, "image_url": None, "error": f"flux {ir.status_code}"}
                url = (ir.json().get("images") or [{}])[0].get("url")
                if url:
                    await db.flux_cache.update_one(
                        {"_id": cache_key},
                        {"$set": {
                            "url": url,
                            "prompt": prompt,
                            "aspect": payload.aspect,
                            "cached_at": datetime.now(timezone.utc).isoformat(),
                        }},
                        upsert=True,
                    )
                return {"idx": idx, "prompt": prompt, "image_url": url, "cached": False}
        except Exception as exc:
            logger.warning(f"[ai-previews] {idx}/{prompt[:30]}: {type(exc).__name__}: {exc}")
            return {"idx": idx, "prompt": prompt, "image_url": None, "error": str(exc)}

    results = await asyncio.gather(*[gen_one(i, p) for i, p in enumerate(payload.prompts)])
    results.sort(key=lambda r: r["idx"])
    return {"previews": results}


# --- Script Engine: async job pattern ---------------------------------------
# Cloudflare-class edge proxies enforce ~60s request timeouts and Claude long-form
# generations take 90-120s, so the POST returns a queued record immediately and a
# background task fills `text` / `status` once Claude responds. The frontend polls
# GET /api/scripts/job/{id} every couple seconds. Mirrors the /api/studio/render
# pattern that's been in production since iteration 1.

LENGTH_VALID = {"short", "medium", "long"}
ANGLE_CATEGORIES = {"curiosity", "contrarian", "how-to", "story", "list"}


def _require_entitlement(user: AuthUser, ent: str) -> None:
    if ent not in user.entitlements:
        raise HTTPException(status_code=403, detail=f"{ent} entitlement required")


# --- Script Engine: STEP 1 — topic angles only -----------------------------

class AnglesRequest(BaseModel):
    topic: str


@api.post("/scripts/angles")
async def scripts_angles(payload: AnglesRequest, user: AuthUser = Depends(current_user)):
    _require_entitlement(user, "base")
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic required")

    raw = await _claude_complete(ANGLES_SYSTEM_PROMPT, build_angles_user_message(topic), user_email=user.email)
    # Tolerate accidental markdown fences or preamble — extract the JSON array.
    text = raw.strip()
    m = re.search(r"\[\s*\{[\s\S]*\}\s*\]", text)
    if not m:
        raise HTTPException(status_code=502, detail="Angle generation failed (no JSON array found)")
    try:
        angles_raw = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Angle generation failed (bad JSON): {e}")

    angles = []
    for a in angles_raw[:5]:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").strip()
        framing = (a.get("framing") or "").strip()
        category = (a.get("category") or "").strip().lower()
        if category not in ANGLE_CATEGORIES:
            category = "curiosity"
        if name and framing:
            angles.append({"name": name, "framing": framing, "category": category})

    if not angles:
        raise HTTPException(status_code=502, detail="No usable angles in response")

    return {"topic": topic, "angles": angles}


# --- Script Engine: STEP 2 — saved angles backlog --------------------------

class SaveAngleRequest(BaseModel):
    topic: str
    angle: dict  # { name, framing, category }


@api.post("/scripts/saved-angles")
async def saved_angles_create(payload: SaveAngleRequest, user: AuthUser = Depends(current_user)):
    _require_entitlement(user, "base")
    a = payload.angle or {}
    if not (a.get("name") and a.get("framing")):
        raise HTTPException(status_code=400, detail="Angle name + framing required")
    rec = {
        "id": str(uuid.uuid4()),
        "user_email": user.email,
        "topic": payload.topic.strip(),
        "angle": {
            "name": str(a.get("name", "")).strip(),
            "framing": str(a.get("framing", "")).strip(),
            "category": (str(a.get("category", "")).strip().lower() or "curiosity"),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.saved_angles.insert_one(rec)
    rec.pop("_id", None)
    return rec


@api.get("/scripts/saved-angles")
async def saved_angles_list(user: AuthUser = Depends(current_user)):
    cursor = db.saved_angles.find({"user_email": user.email}).sort("created_at", -1).limit(100)
    out = []
    async for doc in cursor:
        doc.pop("_id", None)
        out.append(doc)
    return {"items": out}


@api.delete("/scripts/saved-angles/{angle_id}")
async def saved_angles_delete(angle_id: str, user: AuthUser = Depends(current_user)):
    r = await db.saved_angles.delete_one({"id": angle_id, "user_email": user.email})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# --- Script Engine: STEP 2 — full script package locked to a chosen angle --


async def _anthropic_direct_stream(api_key: str, session_id: str, system_prompt: str, user_message: str, script_id: str):
    """BYOK streaming: SSE from Anthropic Messages API, writing accumulated
    text into db.scripts on a throttled cadence (mirrors the Emergent path)."""
    accumulated = ""
    last_write = 0.0
    loop = asyncio.get_event_loop()
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "accept": "text/event-stream",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 8192,
                "system": system_prompt,
                "stream": True,
                "messages": [{"role": "user", "content": user_message}],
            },
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise HTTPException(status_code=502, detail=f"Anthropic stream {resp.status_code}: {body[:200]}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    evt = json.loads(payload)
                except Exception:
                    continue
                if evt.get("type") == "content_block_delta":
                    delta = (evt.get("delta") or {}).get("text") or ""
                    if delta:
                        accumulated += delta
                        now = loop.time()
                        if now - last_write >= 0.25:
                            await db.scripts.update_one(
                                {"id": script_id},
                                {"$set": {"text": accumulated}},
                            )
                            last_write = now
    return accumulated


async def _run_script_job(script_id: str, system_prompt: str, user_message: str, user_email: str | None = None):
    """Background worker — streams Claude's response, writing accumulating text
    back onto the script record so the frontend can render sections as they
    appear (drip / progressive reveal pattern). Falls back to single-shot if
    streaming isn't available on the model."""
    # BYOK: customer's own Anthropic key streams direct from Anthropic
    if user_email:
        try:
            anthropic_key = await get_byok_key(db, user_email, "anthropic")
        except Exception:
            anthropic_key = None
        if anthropic_key:
            try:
                accumulated = await _anthropic_direct_stream(
                    anthropic_key, script_id, system_prompt, user_message, script_id,
                )
                await db.scripts.update_one(
                    {"id": script_id},
                    {"$set": {
                        "status": "complete",
                        "text": accumulated,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return
            except HTTPException as e:
                await db.scripts.update_one(
                    {"id": script_id},
                    {"$set": {
                        "status": "failed",
                        "error": str(e.detail)[:500],
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return
            except Exception as e:  # noqa: BLE001
                await db.scripts.update_one(
                    {"id": script_id},
                    {"$set": {
                        "status": "failed",
                        "error": str(e)[:500],
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return

    from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone  # noqa: E402
    if not EMERGENT_LLM_KEY:
        await db.scripts.update_one(
            {"id": script_id},
            {"$set": {"status": "failed", "error": "LLM key missing",
                      "completed_at": datetime.now(timezone.utc).isoformat()}},
        )
        return
    try:
        chat = (
            LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=script_id,
                system_message=system_prompt,
            )
            .with_model("anthropic", CLAUDE_MODEL)
        )
        accumulated = ""
        last_write = 0.0
        loop = asyncio.get_event_loop()
        async for event in chat.stream_message(UserMessage(text=user_message)):
            if isinstance(event, TextDelta):
                accumulated += event.content
                # Throttle writes to ~250ms to keep Mongo load sane while still
                # feeling live in the UI.
                now = loop.time()
                if now - last_write >= 0.25:
                    await db.scripts.update_one(
                        {"id": script_id},
                        {"$set": {"text": accumulated}},
                    )
                    last_write = now
            elif isinstance(event, StreamDone):
                break
        await db.scripts.update_one(
            {"id": script_id},
            {"$set": {
                "status": "complete",
                "text": accumulated,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except HTTPException as e:
        await db.scripts.update_one(
            {"id": script_id},
            {"$set": {
                "status": "failed",
                "error": e.detail,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception as e:  # noqa: BLE001
        await db.scripts.update_one(
            {"id": script_id},
            {"$set": {
                "status": "failed",
                "error": str(e)[:500],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )


async def _enqueue_script(*, user: AuthUser, mode: str, topic: str, system_prompt: str,
                          user_message: str, extra: dict) -> dict:
    script_id = str(uuid.uuid4())
    rec = {
        "id": script_id,
        "user_email": user.email,
        "mode": mode,
        "topic": topic,
        "status": "running",
        "text": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        **extra,
    }
    await db.scripts.insert_one(rec)
    asyncio.create_task(_run_script_job(script_id, system_prompt, user_message, user_email=user.email))
    rec.pop("_id", None)
    return rec


# --- Script Engine: long-form -----------------------------------------------

class LongScriptRequest(BaseModel):
    topic: str
    length: str = "medium"  # "short" | "medium" | "long"
    angle: Optional[str] = None  # legacy free-text hint
    chosen_angle: Optional[dict] = None  # {name, framing, category} — locked angle from step 1
    include_hooks: bool = True
    include_broll: bool = True
    include_production_notes: bool = True


def _angle_clause(chosen: Optional[dict], free_text: Optional[str]) -> str:
    """Format a chosen angle (preferred) or free-text angle bias into the user msg."""
    if chosen and chosen.get("name") and chosen.get("framing"):
        return (
            f"\n\nLOCKED ANGLE — commit to this fully. Do not propose alternatives:"
            f"\n• Name: {chosen['name']}"
            f"\n• Framing: {chosen['framing']}"
            f"\n• Category: {chosen.get('category', 'curiosity')}"
        )
    if free_text:
        return f"\n\nANGLE BIAS: {free_text}. Commit fully to this angle."
    return ""


@api.post("/scripts/long")
async def scripts_long(payload: LongScriptRequest, user: AuthUser = Depends(current_user)):
    _require_entitlement(user, "base")
    if not payload.topic.strip():
        raise HTTPException(status_code=400, detail="Topic required")
    if payload.length not in LENGTH_VALID:
        raise HTTPException(status_code=400, detail="Invalid length")

    system = build_long_system_prompt(
        payload.length,
        include_hooks=payload.include_hooks,
        include_broll=payload.include_broll,
        include_production_notes=payload.include_production_notes,
    )
    user_msg = f"Generate the full faceless YouTube long-form script package (skipping the angle step) for topic: {payload.topic.strip()}"
    user_msg += _angle_clause(payload.chosen_angle, payload.angle)

    return await _enqueue_script(
        user=user, mode="long", topic=payload.topic,
        system_prompt=system, user_message=user_msg,
        extra={
            "length": payload.length, "angle": payload.angle, "chosen_angle": payload.chosen_angle,
            "include_hooks": payload.include_hooks,
            "include_broll": payload.include_broll,
            "include_production_notes": payload.include_production_notes,
        },
    )


# --- Script Engine: shorts --------------------------------------------------

class ShortsRequest(BaseModel):
    topic: str
    platform: str = "youtube"   # "youtube" | "reels" | "tiktok"
    angle: Optional[str] = None
    chosen_angle: Optional[dict] = None
    sprint: bool = False  # if True, generate a 5-variant Content Sprint instead of a single short


@api.post("/scripts/shorts")
async def scripts_shorts(payload: ShortsRequest, user: AuthUser = Depends(current_user)):
    _require_entitlement(user, "shorts")
    if not payload.topic.strip():
        raise HTTPException(status_code=400, detail="Topic required")
    if payload.platform not in ("youtube", "reels", "tiktok"):
        raise HTTPException(status_code=400, detail="Invalid platform")

    if payload.sprint:
        system = build_sprint_system_prompt(payload.platform)
        user_msg = (
            f"Generate a CONTENT SPRINT — 5 distinct shorts on the topic: {payload.topic.strip()}.\n"
            f"Each variant must use a different angle. Tune everything to {payload.platform}."
        )
        mode = "sprint"
    else:
        system = build_shorts_system_prompt(payload.platform)
        user_msg = f"Generate the full faceless short-form video package (skipping the angle step) for topic: {payload.topic.strip()}"
        user_msg += _angle_clause(payload.chosen_angle, payload.angle)
        mode = "shorts"

    return await _enqueue_script(
        user=user, mode=mode, topic=payload.topic,
        system_prompt=system, user_message=user_msg,
        extra={
            "platform": payload.platform,
            "angle": payload.angle,
            "chosen_angle": payload.chosen_angle,
            "sprint": payload.sprint,
        },
    )


# --- Script Engine: repurpose (long → short) --------------------------------

class RepurposeRequest(BaseModel):
    source_script: str
    platform: str = "youtube"
    angle: Optional[str] = None


@api.post("/scripts/repurpose")
async def scripts_repurpose(payload: RepurposeRequest, user: AuthUser = Depends(current_user)):
    _require_entitlement(user, "shorts")
    if not payload.source_script.strip():
        raise HTTPException(status_code=400, detail="Source script required")
    if payload.platform not in ("youtube", "reels", "tiktok"):
        raise HTTPException(status_code=400, detail="Invalid platform")

    base = build_shorts_system_prompt(payload.platform)
    system = base + "\n\nADDITIONAL CONTEXT: You will be given a long-form script. Derive ONE short from it — don't summarize the whole thing."
    angle_clause = f' biased toward the angle: "{payload.angle}"' if payload.angle else ""
    user_msg = (
        f"Here is the long-form script (sections separated by ### headers):\n\n"
        f"{payload.source_script}\n\n"
        f"Derive ONE faceless short from this source{angle_clause}. Pick a single idea or beat from the source that "
        f"fits and turn it into a complete short package using the exact output structure defined in your system instructions."
    )

    return await _enqueue_script(
        user=user, mode="shorts", topic="(repurposed)",
        system_prompt=system, user_message=user_msg,
        extra={"platform": payload.platform, "angle": payload.angle},
    )


# --- Script Engine: job status ----------------------------------------------

@api.get("/scripts/job/{script_id}")
async def scripts_job_status(script_id: str, user: AuthUser = Depends(current_user)):
    doc = await db.scripts.find_one({"id": script_id, "user_email": user.email})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc.pop("_id", None)
    return doc


# --- Script Engine: history -------------------------------------------------

@api.get("/scripts/history")
async def scripts_history(user: AuthUser = Depends(current_user)):
    cursor = db.scripts.find({"user_email": user.email}).sort("created_at", -1).limit(30)
    items = []
    async for doc in cursor:
        doc.pop("_id", None)
        items.append(doc)
    return {"items": items}


@api.get("/scripts/{script_id}")
async def scripts_get(script_id: str, user: AuthUser = Depends(current_user)):
    doc = await db.scripts.find_one({"id": script_id, "user_email": user.email})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc.pop("_id", None)
    return doc


@api.delete("/scripts/{script_id}")
async def scripts_delete(script_id: str, user: AuthUser = Depends(current_user)):
    r = await db.scripts.delete_one({"id": script_id, "user_email": user.email})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin + Pinball webhook routes — registered before mount.
# ---------------------------------------------------------------------------
register_admin_routes(
    api=api,
    db=db,
    current_user=current_user,
    ADMIN_EMAILS=ADMIN_EMAILS,
    KNOWN_ENTITLEMENTS=KNOWN_ENTITLEMENTS,
    log_activity=_log_activity,
)

# User uploads (B-roll media + recorded voiceovers). Mounted after admin
# so the public /api/files/{id} stream endpoint sits on the same /api router.
register_uploads_routes(
    api=api,
    db=db,
    current_user_dep=current_user,
    require_studio=require_studio,
)

# Thumbnail Engine (OpenAI gpt-image-1 "Premium" + Gemini Nano Banana
# "Fast") for YouTube/Shorts cover images. Mounted on the same /api router
# alongside renders + uploads. Separate GridFS bucket (`thumbnails`) so the
# uploads bucket stays focused on user-supplied B-roll/voiceovers.
from thumbnails_routes import register_thumbnail_routes  # noqa: E402
# Import BYOK helper here (the routes are registered below) so the
# thumbnails rewriter + concepts-from-script can route through a buyer's
# own Anthropic key when present.
from byok_routes import register_byok_routes, get_byok_key  # noqa: E402

register_thumbnail_routes(
    api=api,
    db=db,
    current_user_dep=current_user,
    log_activity=_log_activity,
    emergent_llm_key=EMERGENT_LLM_KEY,
    dev_bypass_email=DEV_BYPASS_EMAIL,
    studio_grant_emails=STUDIO_GRANT_EMAILS,
    get_byok_key=get_byok_key,
)

# License redemption + upgrade-target + admin tier-bump tools (Group D).
# Kept self-contained so server.py doesn't accumulate another 400 LOC and
# the AppSumo launch logic can evolve independently.
from licenses_routes import register_license_routes  # noqa: E402

register_license_routes(
    api=api,
    db=db,
    current_user_dep=current_user,
    require_admin_dep=require_admin,
    log_activity=_log_activity,
    dev_bypass_email=DEV_BYPASS_EMAIL,
    studio_grant_emails=STUDIO_GRANT_EMAILS,
)

# BYOK vault — encrypted Anthropic / OpenAI / HeyGen / fal.ai keys for
# T4 / Founder users. (get_byok_key was imported above for the thumbnails
# rewriter; register_byok_routes mounts /api/user/byok* here.)
# The module also exposes get_byok_key(db, email, service) which the render
# paths call to decide whether to use a customer's key vs the platform key.

register_byok_routes(
    api=api,
    db=db,
    current_user_dep=current_user,
    dev_bypass_email=DEV_BYPASS_EMAIL,
    studio_grant_emails=STUDIO_GRANT_EMAILS,
)

# Roadmap routes — public GET /api/roadmap, admin-gated write endpoints.
# Seeds default items on first read so the /roadmap page never renders blank.
from roadmap_routes import register_roadmap_routes  # noqa: E402

register_roadmap_routes(
    api=api,
    db=db,
    current_user=current_user,
    ADMIN_EMAILS=ADMIN_EMAILS,
)


# ---------------------------------------------------------------------------
# Mount
# ---------------------------------------------------------------------------
app.mount("/api", api)


@app.get("/")
async def root():
    return {"service": "F2F48 Studio API", "status": "ok"}
