"""Faceless Studio provider configuration — kill switches + defaults.

Ships the 2026-07-02 emergency response to fal.ai cost bleed. Charity: "we
need to reduce fal.ai dependency immediately... fal.ai should only be used
when explicitly selected... capped or disabled by admin setting."

Design:
  1. Env vars set the STARTUP default (safe defaults so a fresh deploy
     never accidentally re-enables fal.ai without an admin flip).
  2. Admin can override at runtime via PUT /api/admin/system/faceless-config;
     override persists in `db.system_config` (singleton doc with _id =
     "faceless_provider_config") and wins over env vars.
  3. Public GET /api/config/faceless returns the resolved config so the
     Studio UI can hide the AI engine picker + show a stock-first banner
     without needing admin auth.
  4. `_run_render_faceless` calls `resolve_config(db)` before any provider
     branch. If AI is disabled and `broll_source == "ai"` was requested,
     the render silently downgrades to `default_broll_source` and stamps
     a note on the job doc so admins can see the auto-swap in Activity.

Config schema (all fields optional in DB, defaults come from env):
  {
    "fal_ai_enabled":              bool,   # global fal.ai kill switch
    "ai_visuals_enabled":          bool,   # ANY AI visual generation (fal.ai OR Nano Banana)
    "default_broll_source":        str,    # "pexels" | "pixabay" | "mix" | "uploaded"
    "max_ai_scenes_per_render":    int,    # hard cap; excess scenes auto-fall back to stock
    "max_ai_renders_per_user_day": int,    # daily per-email cap on AI-source renders
    "updated_at":                  str,    # ISO
    "updated_by":                  str,    # admin email
  }

Phase-2 provider abstraction: this module is the seed for a full
`/app/backend/providers/` directory. Once that lands, each provider
(fal.ai, Kinovi, HeyGen, Pexels, ElevenLabs, ...) subclasses a
`BaseProvider` and reads its enabled/capped state from this same
config layer. No provider is called if its `enabled` flag is off,
regardless of who called it.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


CONFIG_DOC_ID = "faceless_provider_config"


def _env_bool(name: str, default: bool) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip())
    except (ValueError, TypeError):
        return default


def env_defaults() -> dict[str, Any]:
    """Read env-var defaults. Called on every config resolution so an env
    change survives a restart without needing a DB row."""
    return {
        # Emergency: default OFF. Admin must explicitly enable fal.ai now.
        "fal_ai_enabled": _env_bool("FAL_AI_ENABLED", False),
        # Nano Banana / any AI visual generation. Kept ON by default because
        # Nano Banana uses the Emergent Universal Key (not fal.ai billing).
        "ai_visuals_enabled": _env_bool("AI_VISUALS_ENABLED", True),
        # Stock-first: default source is Pexels when the user doesn't pick.
        "default_broll_source": (os.environ.get("FACELESS_DEFAULT_SOURCE") or "pexels").strip().lower(),
        # Per-render soft cap on AI-generated scenes. Excess scenes auto-
        # downgrade to `default_broll_source`.
        "max_ai_scenes_per_render": _env_int("MAX_AI_SCENES_PER_RENDER", 2),
        # Daily per-email cap on AI-source renders. 0 = unlimited.
        "max_ai_renders_per_user_day": _env_int("MAX_AI_RENDERS_PER_USER_DAY", 5),
    }


ALLOWED_SOURCES = {"pexels", "pixabay", "mix", "uploaded", "ai"}


async def resolve_config(db) -> dict[str, Any]:
    """Return the effective faceless-provider config (env defaults + DB
    override, DB wins). Never raises — falls back to env defaults on any
    read failure so a hosed Mongo query can't disable the app."""
    cfg = env_defaults()
    try:
        doc = await db.system_config.find_one({"_id": CONFIG_DOC_ID})
    except Exception:
        doc = None
    if doc:
        for k in (
            "fal_ai_enabled", "ai_visuals_enabled",
            "default_broll_source", "max_ai_scenes_per_render",
            "max_ai_renders_per_user_day",
        ):
            if k in doc and doc[k] is not None:
                cfg[k] = doc[k]
    # Sanitize
    if cfg["default_broll_source"] not in ALLOWED_SOURCES:
        cfg["default_broll_source"] = "pexels"
    # `ai` as a default doesn't make sense here — the whole point is stock-first.
    if cfg["default_broll_source"] == "ai":
        cfg["default_broll_source"] = "pexels"
    cfg["max_ai_scenes_per_render"] = max(0, int(cfg["max_ai_scenes_per_render"]))
    cfg["max_ai_renders_per_user_day"] = max(0, int(cfg["max_ai_renders_per_user_day"]))
    return cfg


async def update_config(db, *, updates: dict[str, Any], admin_email: str) -> dict[str, Any]:
    """Upsert the singleton config doc. Only whitelisted fields are honored;
    everything else is dropped silently."""
    now = datetime.now(timezone.utc).isoformat()
    clean: dict[str, Any] = {"updated_at": now, "updated_by": (admin_email or "").lower()}
    if "fal_ai_enabled" in updates:
        clean["fal_ai_enabled"] = bool(updates["fal_ai_enabled"])
    if "ai_visuals_enabled" in updates:
        clean["ai_visuals_enabled"] = bool(updates["ai_visuals_enabled"])
    if "default_broll_source" in updates:
        v = str(updates["default_broll_source"] or "").strip().lower()
        if v in ALLOWED_SOURCES and v != "ai":
            clean["default_broll_source"] = v
    if "max_ai_scenes_per_render" in updates:
        try:
            clean["max_ai_scenes_per_render"] = max(0, int(updates["max_ai_scenes_per_render"]))
        except (ValueError, TypeError):
            pass
    if "max_ai_renders_per_user_day" in updates:
        try:
            clean["max_ai_renders_per_user_day"] = max(0, int(updates["max_ai_renders_per_user_day"]))
        except (ValueError, TypeError):
            pass
    await db.system_config.update_one(
        {"_id": CONFIG_DOC_ID},
        {"$set": clean},
        upsert=True,
    )
    return await resolve_config(db)


async def count_ai_renders_today(db, email: str) -> int:
    """Count `render_started` events with `broll_source: ai` for this email
    since UTC midnight. Used to enforce `max_ai_renders_per_user_day`."""
    if not email:
        return 0
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_iso = today.isoformat()
    try:
        return await db.activity.count_documents({
            "type": "render_started",
            "email": email.lower(),
            "ts": {"$gte": today_iso},
            "detail.broll_source": "ai",
        })
    except Exception:
        return 0
