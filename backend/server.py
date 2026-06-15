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
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
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
load_dotenv()

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
HEYGEN_API_KEY = os.environ.get("HEYGEN_API_KEY", "")
FAL_API_KEY = os.environ.get("FAL_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
NETLIFY_AUTH_URL = os.environ.get("NETLIFY_AUTH_URL", "")
DEV_BYPASS_EMAIL = os.environ.get("DEV_BYPASS_EMAIL", "").strip().lower()
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = FastAPI()  # mounted at /api below


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AuthUser(BaseModel):
    email: str
    entitlements: list[str] = []


class LoginPayload(BaseModel):
    email: str
    cookies: Optional[str] = None  # forwarded raw cookie header from frontend


class RenderRequest(BaseModel):
    mode: str  # "avatar" | "faceless" | "composite"
    script: str
    aspect: str = "9_16"  # "9_16" | "16_9"
    captions: bool = True
    # Avatar mode
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None
    # Faceless mode
    tts_voice_id: Optional[str] = None
    broll_source: Optional[str] = None  # "ai" | "pexels" | "pixabay" | "mix"
    scenes: list[dict] = Field(default_factory=list)
    # Composite mode — interleave avatar talking-head with B-roll cutaways
    broll_cutaway_interval_s: int = 12
    # Caption styling preset (faceless mode only — HeyGen handles its own
    # styling automatically for Avatar). One of: "minimal" (white text only),
    # "boxed" (white text on translucent black box), "bold-yellow" (TikTok
    # style — bold yellow w/ shadow), "outlined" (white text w/ thick black
    # outline). Stored on the doc; consumed by the optional caption-burn-in
    # step at the end of the faceless pipeline.
    caption_style: str = "boxed"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def issue_jwt(email: str, entitlements: list[str]) -> str:
    payload = {
        "email": email,
        "entitlements": entitlements,
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
    return AuthUser(email=payload["email"], entitlements=payload.get("entitlements", []))


def require_studio(user: AuthUser) -> None:
    if "studio" not in user.entitlements:
        raise HTTPException(status_code=403, detail="Studio entitlement required")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@api.get("/health")
async def health():
    return {"ok": True}


@api.post("/auth/check")
async def auth_check(payload: LoginPayload):
    """Verify a user is authenticated.

    Strategy:
    1. If email matches DEV_BYPASS_EMAIL, grant all entitlements (preview only).
    2. Else if cookies provided + NETLIFY_AUTH_URL set, forward to Netlify
       /api/auth-me and trust the response.
    3. Otherwise 401.
    """
    email = payload.email.strip().lower()

    if DEV_BYPASS_EMAIL and email == DEV_BYPASS_EMAIL:
        token = issue_jwt(email, KNOWN_ENTITLEMENTS)
        return {"token": token, "user": {"email": email, "entitlements": KNOWN_ENTITLEMENTS}}

    if not NETLIFY_AUTH_URL or not payload.cookies:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                NETLIFY_AUTH_URL,
                headers={"Cookie": payload.cookies, "Accept": "application/json"},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Auth service unavailable")

    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Not authenticated")

    data = r.json()
    netlify_email = (data.get("email") or "").strip().lower()
    ents = data.get("entitlements") or []
    if not netlify_email or netlify_email != email:
        raise HTTPException(status_code=401, detail="Email mismatch")

    token = issue_jwt(netlify_email, ents)
    return {"token": token, "user": {"email": netlify_email, "entitlements": ents}}


@api.get("/auth/me")
async def auth_me(user: AuthUser = Depends(current_user)):
    return {
        "email": user.email,
        "entitlements": user.entitlements,
        "isAdmin": user.email.lower() in ADMIN_EMAILS,
    }


# ---------------------------------------------------------------------------
# HeyGen — avatars + voices (with 24h Mongo cache)
# ---------------------------------------------------------------------------
async def _heygen_get(path: str) -> dict:
    if not HEYGEN_API_KEY:
        raise HTTPException(status_code=500, detail="HeyGen key missing")
    async with httpx.AsyncClient(timeout=30) as client:
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


@api.get("/studio/avatars")
async def studio_avatars(user: AuthUser = Depends(current_user)):
    require_studio(user)

    async def fetch():
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
                "aspect": aspect,  # "portrait" | "landscape" | "both" — used by the picker filter
            })
        return out

    avatars = await _cached("heygen_avatars_v2", 24, fetch)
    return {"avatars": avatars}


@api.get("/studio/voices")
async def studio_voices(user: AuthUser = Depends(current_user)):
    require_studio(user)

    async def fetch():
        raw = await _heygen_get("/voices")
        voices = (raw.get("data") or {}).get("voices") or []
        out = []
        for v in voices:
            out.append({
                "id": v.get("voice_id"),
                "name": v.get("name") or v.get("voice_id"),
                "gender": (v.get("gender") or "").lower() or "other",
                "language": v.get("language") or "",
                "preview_audio": v.get("preview_audio"),
            })
        return out

    voices = await _cached("heygen_voices_v1", 24, fetch)
    return {"voices": voices}


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
    if user.email.lower() not in ADMIN_EMAILS:
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
                params={"query": q, "orientation": orientation, "per_page": 12},
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
                params={"key": PIXABAY_API_KEY, "q": q, "per_page": 12},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="Pixabay error")
            for v in r.json().get("hits") or []:
                videos = v.get("videos") or {}
                pick = videos.get("medium") or videos.get("small") or videos.get("large")
                if not pick:
                    continue
                results.append({
                    "id": f"pix-{v.get('id')}",
                    "thumb": f"https://i.vimeocdn.com/video/{v.get('picture_id')}_295x166.jpg" if v.get("picture_id") else None,
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
        # Kokoro TTS + Flux per-scene + compose
        scene_count = max(1, len(payload.scenes) or int(duration_s / 8))
        # ~$0.005 / 1k chars for Kokoro-class TTS — coefficient deliberately
        # conservative (real renders may cost less but we'd rather reject
        # a borderline payload than surprise-charge the user above the cap).
        cents += (len(payload.script) / 1000.0) * 5.0  # TTS
        cents += scene_count * 4.0                     # Flux images
        cents += 2.0                                   # compose overhead
    elif payload.mode == "composite":
        # Avatar talking-head + B-roll cutaway every N seconds
        cents += duration_min * 30.0 + 5.0             # HeyGen base
        cutaway_count = max(1, int(duration_s / max(1, payload.broll_cutaway_interval_s)))
        cents += cutaway_count * 4.0                   # Flux per cutaway
        cents += 3.0                                   # extra compose overhead
    else:
        return 0
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

    if not HEYGEN_API_KEY:
        await _finalize(job_id, ok=False, url=None, actual_cost_cents=0)
        return
    captions_on = bool(job.get("captions", True))

    # ---- Stage 1/3: voiceover ----
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {"status": "voiceover", "progress": 20, "progress_label": "Preparing voiceover…"}},
    )
    await asyncio.sleep(1.5)

    # ---- Stage 2/3: submit to HeyGen. Try v3 first (cleaner crop + caption
    # burn-in for Avatar IV/V); on the explicit "does not support Avatar IV"
    # error, transparently fall back to the legacy v2 endpoint (Avatar III
    # avatars). The customer never sees the fallback. ----
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
        if captions_on:
            v3_body["caption"] = {"file_format": "srt", "style": "default"}
        r = await client.post(
            "https://api.heygen.com/v3/videos",
            headers={"X-Api-Key": HEYGEN_API_KEY, "Accept": "application/json"},
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
                "caption": captions_on,
            }
            r2 = await client.post(
                "https://api.heygen.com/v2/video/generate",
                headers={"X-Api-Key": HEYGEN_API_KEY, "Accept": "application/json"},
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
        for tick in range(60):
            await asyncio.sleep(5)
            # Animate the in-flight progress so it doesn't feel stuck during
            # the long HeyGen render wait. Walks 50→85% across the poll window.
            progress_now = min(85, 50 + tick)
            label_now = ("Polishing avatar…" if tick > 6
                         else "Rendering avatar frames…" if tick > 2
                         else "Finalizing voiceover…")
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {"progress": progress_now, "progress_label": label_now}},
            )
            if used_endpoint == "v3":
                s = await client.get(
                    f"https://api.heygen.com/v3/videos/{video_id}",
                    headers={"X-Api-Key": HEYGEN_API_KEY},
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
                final_url = (d.get("captioned_video_url") if captions_on else None) or d.get("video_url")
                if final_url:
                    actual_cost_cents += int(round(_estimate_duration_seconds(job["script"]) / 60.0 * 30.0))
                    await _finalize(job_id, ok=True, url=final_url, actual_cost_cents=actual_cost_cents)
                    return
            else:  # v2 polling
                s = await client.get(
                    f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                    headers={"X-Api-Key": HEYGEN_API_KEY},
                )
                d = (s.json() or {}).get("data") or {}
                if d.get("status") == "completed":
                    actual_cost_cents += int(round(_estimate_duration_seconds(job["script"]) / 60.0 * 30.0))
                    await _finalize(job_id, ok=True, url=d.get("video_url"), actual_cost_cents=actual_cost_cents)
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
            "error": "HeyGen polling timed out after 5 minutes",
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

    if not FAL_API_KEY:
        await _finalize(job_id, ok=False, url=None, actual_cost_cents=0)
        return

    fal_headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

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
            req_id = sub.json().get("request_id")
            if not req_id:
                await db.renders.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "error": "Compose returned no request_id",
                        "actual_cost_cents": actual_cost_cents,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                return None
            status_url = f"https://queue.fal.run/{model_id}/requests/{req_id}/status"
            result_url = f"https://queue.fal.run/{model_id}/requests/{req_id}"
            deadline = asyncio.get_event_loop().time() + max_wait_s
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(3)
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

    # 1) Kokoro TTS — single call
    await _set_progress(20, "Generating voiceover with Kokoro TTS…")
    async with httpx.AsyncClient(timeout=120) as client:
        tts_r = await client.post(
            f"https://fal.run/{_kokoro_endpoint(job.get('tts_voice_id') or 'af_heart')}",
            headers=fal_headers,
            json={"prompt": job["script"], "voice": job.get("tts_voice_id") or "af_heart"},
        )
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
        audio_url = tts_json.get("audio_url") or (tts_json.get("audio") or {}).get("url")
        actual_cost_cents += int((len(job["script"]) / 1000.0) * 5)

        # 2) Per-scene visuals. AI scenes use Flux 1.1 Pro; stock scenes use
        # their pre-picked URL. We surface per-scene progress so the user
        # knows exactly which scene is rendering.
        await _set_progress(30, f"Generating scene visuals (0 of {n_scenes})…", status="visuals")
        image_urls: list = [None] * len(scenes)

        async def gen_image(idx: int, prompt: str):
            ir = await client.post(
                "https://fal.run/fal-ai/flux-pro/v1.1",
                headers=fal_headers,
                json={
                    "prompt": prompt,
                    "image_size": "portrait_16_9" if job["aspect"] == "9_16" else "landscape_16_9",
                },
            )
            if ir.status_code != 200:
                return None
            data = ir.json()
            return (data.get("images") or [{}])[0].get("url")

        # Resolve URLs per scene. If broll_source==ai (or scene-level AI),
        # call Flux; else use scene.video_url / scene.url from the picker.
        global_source = job.get("broll_source") or "ai"
        ai_tasks = []
        for i, s in enumerate(scenes):
            effective_src = s.get("source") or global_source
            if effective_src == "ai":
                ai_tasks.append((i, s.get("prompt", "")))
            else:
                image_urls[i] = s.get("video_url") or s.get("url") or s.get("thumb")

        completed = 0
        total_ai = len(ai_tasks)
        # Fire all Flux jobs in parallel but tick progress as each one finishes.
        async def gen_and_tick(idx: int, prompt: str):
            nonlocal completed
            url = await gen_image(idx, prompt)
            image_urls[idx] = url
            completed += 1
            base = 30
            span = 25  # 30 → 55%
            pct = base + int(span * (completed / max(1, total_ai)))
            await _set_progress(pct, f"Generating scene visuals ({completed} of {n_scenes}) · Flux 1.1 Pro")
            return url

        if ai_tasks:
            await asyncio.gather(*[gen_and_tick(i, p) for i, p in ai_tasks])
            actual_cost_cents += total_ai * 4

    # 3) Optional caption transcript (Whisper) — best-effort
    captions_srt = None
    if job.get("captions", True) and audio_url:
        await _set_progress(60, "Transcribing audio for captions…")
        try:
            wres = await _fal_queue_run(
                "fal-ai/wizper",
                {"audio_url": audio_url, "task": "transcribe", "chunk_level": "segment"},
                max_wait_s=180,
            )
            if wres and wres.get("chunks"):
                def _fmt_srt_ts(s):
                    h = int(s // 3600)
                    m = int((s % 3600) // 60)
                    sec = s - h * 3600 - m * 60
                    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")
                lines = []
                for i, c in enumerate(wres["chunks"], start=1):
                    text = (c.get("text") or "").strip()
                    if not text:
                        continue
                    ts = c.get("timestamp") or [0, 0]
                    lines.append(f"{i}\n{_fmt_srt_ts(ts[0])} --> {_fmt_srt_ts(ts[1])}\n{text}\n")
                captions_srt = "\n".join(lines) if lines else None
                actual_cost_cents += 1
        except Exception:
            captions_srt = None  # best-effort

    # 4) Compose — fal.ai ffmpeg-api/compose.
    #
    # Track type must MATCH the underlying media:
    #   - "image" for Flux PNG/JPG stills (worker holds each frame for `duration`)
    #   - "video" for Pexels/Pixabay MP4 clips (worker copies frames natively)
    # Putting an image URL on a "video" track makes the worker grind trying to
    # decode the PNG as a video file — that's the 10+ minute compose timeout
    # that's been blocking faceless renders.
    #
    # For mixed AI+stock scenes we lay each scene on its own track at a
    # non-overlapping timestamp so each track can be type-correct.
    # `timestamp` + `duration` are in MILLISECONDS per fal.ai's Keyframe schema.
    tracks: list = []
    total_video_ms = 0
    scene_meta: list = []  # (idx, url, is_video, src_kind)
    for i, s in enumerate(scenes):
        url = image_urls[i]
        if not url:
            continue
        effective_src = s.get("source") or global_source
        is_video = effective_src in ("pexels", "pixabay")
        scene_meta.append((i, url, is_video, effective_src))

    if scene_meta:
        target_ms = int(_estimate_duration_seconds(job["script"]) * 1000)
        # Per-scene duration: even split of audio across scenes, but at
        # least 1.5s per scene so transitions don't blur and at most 8s so
        # the worker doesn't have to encode huge segments for tiny audio.
        per_dur_ms = max(1500, min(8000, target_ms // max(1, len(scene_meta))))

        # Bucket scenes by track type when they're homogeneous (faster encode
        # — single track with N keyframes). Fall back to per-scene tracks
        # when the user mixed AI + stock in a single render.
        all_images = all(not v for _, _, v, _ in scene_meta)
        all_videos = all(v for _, _, v, _ in scene_meta)

        if all_images or all_videos:
            ttype = "image" if all_images else "video"
            keyframes = []
            cursor_ms = 0
            for _, url, _, _ in scene_meta:
                keyframes.append({"url": url, "timestamp": cursor_ms, "duration": per_dur_ms})
                cursor_ms += per_dur_ms
            tracks.append({"id": "main", "type": ttype, "keyframes": keyframes})
            total_video_ms = cursor_ms
        else:
            cursor_ms = 0
            for idx, (_, url, is_video, _) in enumerate(scene_meta):
                tracks.append({
                    "id": f"scene-{idx}",
                    "type": "video" if is_video else "image",
                    "keyframes": [{"url": url, "timestamp": cursor_ms, "duration": per_dur_ms}],
                })
                cursor_ms += per_dur_ms
            total_video_ms = cursor_ms

    if audio_url:
        audio_dur_ms = max(5000, total_video_ms or int(_estimate_duration_seconds(job["script"]) * 1000))
        tracks.append({
            "id": "audio",
            "type": "audio",
            "keyframes": [{"url": audio_url, "timestamp": 0, "duration": audio_dur_ms}],
        })

    # Granular composing progress with sub-step labels so the UI never looks stuck.
    await _set_progress(70, f"Stitching scene 1 of {n_scenes}…", status="composing")

    # Spawn a background tick task that walks per-scene labels while compose runs.
    stop_ticking = asyncio.Event()

    async def tick_compose_progress():
        # Walks "Stitching scene N of M…" labels at a slow cadence so the user
        # always sees motion in the label even though we only get one final
        # callback from fal.ai when the whole job finishes.
        scene_idx = 1
        progress_pct = 70
        while not stop_ticking.is_set():
            try:
                await asyncio.wait_for(stop_ticking.wait(), timeout=4.0)
                break
            except asyncio.TimeoutError:
                pass
            scene_idx = min(n_scenes, scene_idx + 1)
            progress_pct = min(90, progress_pct + 2)
            try:
                await _set_progress(progress_pct, f"Stitching scene {scene_idx} of {n_scenes}…")
            except Exception:
                pass

    ticker_task = asyncio.create_task(tick_compose_progress())
    try:
        compose_res = await _fal_queue_run(
            "fal-ai/ffmpeg-api/compose",
            {"tracks": tracks},
            max_wait_s=600,
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

    # 5) Optional caption burn-in. Best-effort 2nd compose pass with SRT.
    out_url = composed_url
    if captions_srt and composed_url:
        await _set_progress(92, "Burning in captions…")
        try:
            # Single video keyframe spanning the full composed clip — duration
            # in MILLISECONDS to match the compose schema fix above.
            cap_res = await _fal_queue_run(
                "fal-ai/ffmpeg-api/compose",
                {
                    "tracks": [
                        {
                            "id": "v",
                            "type": "video",  # composed_url IS a video — keep "video" type here
                            "keyframes": [{
                                "url": composed_url,
                                "timestamp": 0,
                                "duration": max(5000, total_video_ms or 20000),
                            }],
                        },
                    ],
                    "srt": captions_srt,
                },
                max_wait_s=300,
            )
            if cap_res:
                cap_url = cap_res.get("video_url") or (cap_res.get("video") or {}).get("url")
                if cap_url:
                    out_url = cap_url
                    actual_cost_cents += 2
        except Exception:
            pass  # ship the un-captioned video on failure
    await _finalize(job_id, ok=True, url=out_url, actual_cost_cents=actual_cost_cents)


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
        "broll_cutaway_interval_s": payload.broll_cutaway_interval_s,
        "caption_style": payload.caption_style,
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
    is_admin = user.email.lower() in ADMIN_EMAILS
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
    is_admin = user.email.lower() in ADMIN_EMAILS
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


async def _claude_complete(system_prompt: str, user_message: str, session_id: str | None = None) -> str:
    """Single-shot Claude completion using the Emergent universal LLM key."""
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

    text = await _claude_complete(
        BROLL_PROMPTS_SYSTEM,
        f"Script:\n\n{payload.script.strip()}",
    )
    # Parse: one per line, drop blanks, strip bullets/quotes/numbering
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Strip leading "1.", "-", "*", numerals, and surrounding quotes
        line = line.lstrip("0123456789. -*•").strip().strip('"\u201c\u201d').strip()
        if line:
            out.append(line)
    return {"prompts": out[:12]}


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

    raw = await _claude_complete(ANGLES_SYSTEM_PROMPT, build_angles_user_message(topic))
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


async def _run_script_job(script_id: str, system_prompt: str, user_message: str):
    """Background worker — runs Claude, writes result back onto the script record."""
    try:
        text = await _claude_complete(system_prompt, user_message, session_id=script_id)
        await db.scripts.update_one(
            {"id": script_id},
            {"$set": {
                "status": "complete",
                "text": text,
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
    asyncio.create_task(_run_script_job(script_id, system_prompt, user_message))
    rec.pop("_id", None)
    return rec


# --- Script Engine: long-form -----------------------------------------------

class LongScriptRequest(BaseModel):
    topic: str
    length: str = "medium"  # "short" | "medium" | "long"
    angle: Optional[str] = None  # legacy free-text hint
    chosen_angle: Optional[dict] = None  # {name, framing, category} — locked angle from step 1


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

    system = build_long_system_prompt(payload.length)
    user_msg = f"Generate the full faceless YouTube long-form script package (skipping the angle step) for topic: {payload.topic.strip()}"
    user_msg += _angle_clause(payload.chosen_angle, payload.angle)

    return await _enqueue_script(
        user=user, mode="long", topic=payload.topic,
        system_prompt=system, user_message=user_msg,
        extra={"length": payload.length, "angle": payload.angle, "chosen_angle": payload.chosen_angle},
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
# Mount
# ---------------------------------------------------------------------------
app.mount("/api", api)


@app.get("/")
async def root():
    return {"service": "F2F48 Studio API", "status": "ok"}
