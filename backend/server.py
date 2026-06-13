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
DRY_RUN_RENDERS = os.environ.get("DRY_RUN_RENDERS", "true").lower() == "true"
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "drcharitycampbell@gmail.com").split(",")
    if e.strip()
}
# Hard cap — any render whose estimated cost exceeds this in cents is rejected.
# Composite renders need the headroom; single-mode renders won't hit it.
RENDER_COST_CAP_CENTS = int(os.environ.get("RENDER_COST_CAP_CENTS", "150"))

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
    # Admin-only override. When None, falls back to the env default. When False
    # but caller is not an admin, the request is rejected (customers MUST run
    # against the env default — they can't elect to dry-run their own renders).
    dry_run: Optional[bool] = None


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
    return {"ok": True, "dry_run": DRY_RUN_RENDERS}


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
        "dryRunDefault": DRY_RUN_RENDERS,
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
            out.append({
                "id": a.get("avatar_id"),
                "name": a.get("avatar_name") or a.get("avatar_id"),
                "preview_image_url": a.get("preview_image_url"),
                "preview_video_url": a.get("preview_video_url"),
                "gender": (a.get("gender") or "").lower() or "other",
                "premium": bool(a.get("premium")),
            })
        return out

    avatars = await _cached("heygen_avatars_v1", 24, fetch)
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
    """Dispatch to the per-mode render pipeline.

    Each pipeline reads its own `dry_run` flag off the job doc — when True
    (default for dev/preview) every external API call is stubbed and the
    pipeline writes a sample MP4 + a $0.00 actual cost. When False the real
    HeyGen / fal.ai calls fire and actual_cost_cents is accumulated as the
    pipeline runs.
    """
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
# Stage walker shared by all pipelines. Sleeps shorter in dry-run.
# ---------------------------------------------------------------------------
async def _walk_stages(job_id: str, stages, dry_run: bool):
    for status, progress, label in stages:
        await asyncio.sleep(1.0 if dry_run else 4.0)
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


SAMPLE_VIDEO_URL = "https://www.w3schools.com/html/mov_bbb.mp4"


# ---------------------------------------------------------------------------
# HeyGen Avatar pipeline (DRY_RUN scaffolding)
# Full real-API code is written below but every external call is gated behind
# `dry_run`. To go live, flip dry_run False on the job and the same code runs
# unchanged.
# ---------------------------------------------------------------------------
async def _run_render_avatar(job: dict):
    job_id = job["id"]
    dry_run = job.get("dry_run", True)
    actual_cost_cents = 0

    await _walk_stages(job_id, [
        ("voiceover", 25, "Generating voiceover…"),
        ("avatar", 55, "Generating avatar video…"),
        ("polling", 85, "Finalizing video…"),
    ], dry_run)

    if dry_run:
        await _finalize(job_id, ok=True, url=SAMPLE_VIDEO_URL, actual_cost_cents=0)
        return

    # ---- REAL HeyGen v2 video generation flow (not executed in dry-run) ----
    if not HEYGEN_API_KEY:
        await _finalize(job_id, ok=False, url=None, actual_cost_cents=0)
        return
    async with httpx.AsyncClient(timeout=60) as client:
        # 1) Submit
        body = {
            "video_inputs": [{
                "character": {"type": "avatar", "avatar_id": job["avatar_id"], "avatar_style": "normal"},
                "voice": {"type": "text", "voice_id": job["voice_id"], "input_text": job["script"]},
            }],
            "dimension": {"width": 1080 if job["aspect"] == "16_9" else 720,
                          "height": 1920 if job["aspect"] == "9_16" else 1080},
        }
        # Captions: send a caption-object with an explicit burn-in style so
        # HeyGen renders subtitles INTO the video (not just a sidecar SRT).
        # Sending bool true also works for legacy plans — the object form is
        # required for newer HeyGen accounts to actually burn captions in.
        if job.get("captions", True):
            body["caption"] = {
                "file_format": "srt",
                "style": {
                    "font_size": 48,
                    "color": "#FFFFFF",
                    "background_color": "#000000",
                    "alignment": "center",
                    "position": "bottom",
                },
            }
        r = await client.post(
            "https://api.heygen.com/v2/video/generate",
            headers={"X-Api-Key": HEYGEN_API_KEY, "Accept": "application/json"},
            json=body,
        )
        if r.status_code != 200:
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {
                    "status": "failed",
                    "error": f"HeyGen API error {r.status_code}: {r.text[:300]}",
                    "actual_cost_cents": actual_cost_cents,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return
        video_id = r.json()["data"]["video_id"]
        # 2) Poll
        for _ in range(60):  # max ~5 min
            await asyncio.sleep(5)
            s = await client.get(
                f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                headers={"X-Api-Key": HEYGEN_API_KEY},
            )
            d = s.json().get("data", {})
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
# fal.ai Faceless pipeline (DRY_RUN scaffolding)
# Real flow: Kokoro TTS → Flux per-scene images → ffmpeg compose.
# ---------------------------------------------------------------------------
async def _run_render_faceless(job: dict):
    job_id = job["id"]
    dry_run = job.get("dry_run", True)
    scenes = job.get("scenes") or []
    actual_cost_cents = 0

    await _walk_stages(job_id, [
        ("voiceover", 20, "Generating voiceover…"),
        ("visuals", 55, f"Generating {max(1, len(scenes))} scene visuals…"),
        ("composing", 85, "Stitching b-roll together…"),
    ], dry_run)

    if dry_run:
        await _finalize(job_id, ok=True, url=SAMPLE_VIDEO_URL, actual_cost_cents=0)
        return

    if not FAL_API_KEY:
        await _finalize(job_id, ok=False, url=None, actual_cost_cents=0)
        return

    fal_headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}

    async def _fal_queue_run(model_id: str, payload: dict, *, max_wait_s: int = 600) -> Optional[dict]:
        """Submit a job to fal.ai's queue endpoint and poll for completion.
        Returns the final response JSON, or None on failure (job already
        finalized with a descriptive error). Replaces the synchronous
        `fal.run/<model>` call which times out at 120s on long compose jobs.
        """
        async with httpx.AsyncClient(timeout=30) as qclient:
            sub = await qclient.post(f"https://queue.fal.run/{model_id}", headers=fal_headers, json=payload)
            if sub.status_code not in (200, 202):
                await db.renders.update_one(
                    {"id": job_id},
                    {"$set": {
                        "status": "failed",
                        "error": f"fal.ai {model_id} submit error {sub.status_code}: {sub.text[:300]}",
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
                        "error": f"fal.ai {model_id} returned no request_id",
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
                                "error": f"fal.ai {model_id} fetch result {res.status_code}: {res.text[:300]}",
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
                            "error": f"fal.ai {model_id} returned FAILED: {str(err)[:300]}",
                            "actual_cost_cents": actual_cost_cents,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                    return None
            await db.renders.update_one(
                {"id": job_id},
                {"$set": {
                    "status": "failed",
                    "error": f"fal.ai {model_id} polling timed out after {max_wait_s}s",
                    "actual_cost_cents": actual_cost_cents,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return None

    # 1) Kokoro TTS — single call (fast enough to keep synchronous)
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
                    "error": f"fal.ai Kokoro TTS error {tts_r.status_code}: {tts_r.text[:300]}",
                    "actual_cost_cents": actual_cost_cents,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return
        audio_url = tts_r.json().get("audio_url") or tts_r.json().get("audio", {}).get("url")
        actual_cost_cents += int((len(job["script"]) / 1000.0) * 5)

        # 2) Flux per-scene images (parallel) — short jobs, sync is fine
        image_urls = []
        if (job.get("broll_source") or "ai") == "ai":
            async def gen_image(prompt):
                ir = await client.post(
                    "https://fal.run/fal-ai/flux-pro/v1.1",
                    headers=fal_headers,
                    json={"prompt": prompt, "image_size": "portrait_16_9" if job["aspect"] == "9_16" else "landscape_16_9"},
                )
                return ir.json().get("images", [{}])[0].get("url") if ir.status_code == 200 else None
            image_urls = await asyncio.gather(*[gen_image(s.get("prompt", "")) for s in scenes])
            actual_cost_cents += len(scenes) * 4
        # else: use scene["url"] already populated by Pexels/Pixabay picker

    # 3) Optional captions — transcribe TTS audio with Whisper for subtitle
    # track. Best-effort — if Whisper fails, render without captions rather
    # than failing the whole job.
    subtitles = None
    if job.get("captions", True) and audio_url:
        try:
            wres = await _fal_queue_run(
                "fal-ai/wizper",
                {"audio_url": audio_url, "task": "transcribe", "chunk_level": "word"},
                max_wait_s=180,
            )
            if wres and wres.get("chunks"):
                subtitles = [
                    {"text": c.get("text", "").strip(),
                     "start_time": c.get("timestamp", [0, 0])[0],
                     "end_time": c.get("timestamp", [0, 0])[1]}
                    for c in wres["chunks"] if c.get("text", "").strip()
                ]
                actual_cost_cents += 1  # whisper-class ~$0.01
        except Exception:
            subtitles = None  # best-effort; continue without captions

    # 4) Compose — fal.ai ffmpeg async queue (the synchronous fal.run/.../compose
    # was hitting a 120s ReadTimeout on multi-scene jobs).
    tracks = []
    if scenes:
        # Build the video track from per-scene clips, each ~4s by default
        per_dur = max(2, int(_estimate_duration_seconds(job["script"]) / max(1, len(scenes))))
        keyframes = []
        cursor = 0.0
        for i, s in enumerate(scenes):
            url = image_urls[i] if image_urls and i < len(image_urls) else s.get("url")
            if not url:
                continue
            keyframes.append({"url": url, "timestamp": cursor, "duration": per_dur})
            cursor += per_dur
        if keyframes:
            tracks.append({"id": "video", "type": "video", "keyframes": keyframes})
    if audio_url:
        tracks.append({"id": "audio", "type": "audio", "keyframes": [{"url": audio_url, "timestamp": 0}]})
    if subtitles:
        tracks.append({"id": "captions", "type": "subtitles", "keyframes": [
            {"text": s["text"], "timestamp": s["start_time"], "duration": max(0.1, s["end_time"] - s["start_time"])}
            for s in subtitles
        ]})

    compose_res = await _fal_queue_run(
        "fal-ai/ffmpeg-api/compose",
        {"tracks": tracks},
        max_wait_s=600,
    )
    actual_cost_cents += 2
    if not compose_res:
        return  # _fal_queue_run already finalized the job with an error
    out_url = compose_res.get("video_url") or (compose_res.get("video") or {}).get("url")
    await _finalize(job_id, ok=True, url=out_url, actual_cost_cents=actual_cost_cents)


# ---------------------------------------------------------------------------
# Composite Avatar + B-roll cutaways pipeline (DRY_RUN scaffolding)
# Real flow: render HeyGen talking-head as base track + Flux B-roll cutaways
# every N seconds + ffmpeg overlay.
# ---------------------------------------------------------------------------
async def _run_render_composite(job: dict):
    job_id = job["id"]
    dry_run = job.get("dry_run", True)
    duration_s = _estimate_duration_seconds(job["script"])
    interval_s = max(1, int(job.get("broll_cutaway_interval_s", 12)))
    cutaway_count = max(1, int(duration_s / interval_s))

    await _walk_stages(job_id, [
        ("avatar", 25, "Generating avatar video…"),
        ("cutaways", 55, f"Generating {cutaway_count} b-roll cutaways…"),
        ("composing", 85, "Composing final video…"),
    ], dry_run)

    if dry_run:
        await _finalize(job_id, ok=True, url=SAMPLE_VIDEO_URL, actual_cost_cents=0)
        return

    # Real path: render HeyGen talking-head as base track, generate
    # cutaway_count Flux B-roll images, then call ffmpeg overlay endpoint
    # with cutaway timestamps. Not yet implemented — flip dry_run off only
    # AFTER this branch is filled in. Until then surface a clear error.
    await db.renders.update_one(
        {"id": job_id},
        {"$set": {
            "status": "failed",
            "error": "Composite real-render not implemented yet — keep dry_run on for composite mode.",
            "actual_cost_cents": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


@api.post("/studio/render/estimate")
async def studio_render_estimate(payload: RenderRequest, user: AuthUser = Depends(current_user)):
    """Returns the conservative cost estimate + cap for a candidate render.
    Used by the admin 'Use real render' toggle to show '~$X.XX' live as the
    user changes mode/aspect/script length."""
    require_studio(user)
    cents = estimate_render_cost_cents(payload)
    return {
        "estimated_cost_cents": cents,
        "estimated_cost_dollars": round(cents / 100.0, 2),
        "cap_cents": RENDER_COST_CAP_CENTS,
        "cap_dollars": round(RENDER_COST_CAP_CENTS / 100.0, 2),
        "exceeds_cap": cents > RENDER_COST_CAP_CENTS,
        "dry_run_default": DRY_RUN_RENDERS,
        "is_admin": user.email.lower() in ADMIN_EMAILS,
    }


@api.post("/studio/render")
async def studio_render(payload: RenderRequest, user: AuthUser = Depends(current_user)):
    require_studio(user)
    if payload.mode not in ("avatar", "faceless", "composite"):
        raise HTTPException(status_code=400, detail="Bad mode")
    if not payload.script.strip():
        raise HTTPException(status_code=400, detail="Script required")

    is_admin = user.email.lower() in ADMIN_EMAILS
    # Resolve effective dry_run:
    # - Customers always run against the env default. We ignore any dry_run
    #   override they try to send so a stray flag in a request body can't
    #   turn off real renders for paying customers (or vice-versa).
    # - Admins may override per-request; default is the env value when None.
    if is_admin and payload.dry_run is not None:
        effective_dry_run = payload.dry_run
    else:
        effective_dry_run = DRY_RUN_RENDERS

    # Cost guard — applies even when dry_run is True so admins can't
    # accidentally fire a $5 sprint by toggling dry_run off after the
    # fact. The cap is the cents value at the top of this file.
    estimated_cents = estimate_render_cost_cents(payload)
    if estimated_cents > RENDER_COST_CAP_CENTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Render rejected: estimated ${estimated_cents/100:.2f} exceeds "
                f"hard cap of ${RENDER_COST_CAP_CENTS/100:.2f}. "
                f"Shorten the script or pick a cheaper mode."
            ),
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
        "status": "queued",
        "progress": 5,
        "progress_label": "Queued…",
        "result_url": None,
        "error": None,
        "dry_run": effective_dry_run,
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
        "dry_run": effective_dry_run,
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
    if doc["status"] not in ("complete", "failed"):
        raise HTTPException(status_code=409, detail="In-progress renders cannot be deleted")
    await db.renders.delete_one({"id": job_id, "user_email": user.email})
    await _log_activity("studio_render_deleted", user.email, {"job_id": job_id})
    return {"ok": True}


class BulkDeleteRequest(BaseModel):
    ids: list[str]


@api.post("/studio/render/bulk-delete")
async def studio_render_bulk_delete(payload: BulkDeleteRequest, user: AuthUser = Depends(current_user)):
    """Delete multiple completed/failed renders in one shot. In-progress
    renders are silently skipped to avoid orphaning background tasks."""
    require_studio(user)
    if not payload.ids:
        return {"deleted": 0}
    res = await db.renders.delete_many({
        "id": {"$in": payload.ids},
        "user_email": user.email,
        "status": {"$in": ["complete", "failed"]},
    })
    await _log_activity("studio_render_bulk_deleted", user.email, {
        "requested": len(payload.ids),
        "deleted": res.deleted_count,
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
