"""AppSumo Licensing API v2 integration.

Endpoints (all on the shared `api` sub-app from server.py, mounted at /api):

  - POST /api/appsumo-webhook?token=...   — AppSumo license event receiver.
    Handles purchase / activate / upgrade / downgrade / deactivate / migrate
    and the Partner Portal's test pings. Token-gated (same pattern as the
    Pinball webhook) with optional HMAC SHA256 verification on top.
  - POST /api/appsumo/redeem              — OAuth code exchange. Called by the
    /redeem page after AppSumo redirects the buyer with ?code=. Exchanges the
    code for the buyer's license_key, links it to their email, and grants
    entitlements in db.buyers so the normal email sign-in works.
  - GET  /api/admin/appsumo/licenses      — admin-gated license search, so
    support can look up any license_key (AppSumo requires partners to keep
    license keys searchable — AppSumo itself never stores customer emails).
  - GET/PUT /api/admin/appsumo/config     — admin-gated settings. Charity's
    deployment platform doesn't expose env-var editing to her, so OAuth
    credentials + the API key are stored in db.settings and edited from the
    Admin → AppSumo tab instead. Resolution order: db.settings > env > default.

Storage:
  - db.settings ("appsumo")  — webhook_token / api_key / client_id /
    client_secret / redirect_uri overrides.
  - db.appsumo_licenses      — one doc per license_key (the durable record).
  - db.activity              — every webhook + redemption logged via
    log_activity, same trail the Admin → Activity UI already reads.

Tier model (per Charity's AppSumo listing, 2026-07-02):
  - ALL tiers include the Long-form Script Engine + Shorts Engine
    → entitlements ["base", "shorts"].
  - Tier 1 ($49):  scripts only.
  - Tier 2 ($179): + Studio ("studio" entitlement).
  - Tier 3 ($349): + Studio.
  Per-tier limits from the listing (Sprint gate, faceless/avatar renders per
  month) are enforced at the render + shorts endpoints in server.py via
  get_buyer_appsumo_limits() — Charity approved this on 2026-07-02. Limits
  apply only to buyers whose access came from AppSumo (source == "appsumo");
  Pinball/admin-granted customers stay unlimited. The listing's thumbnail
  quota and "Connected AI accounts" rows concern features that don't exist
  in this codebase copy (they live in Emergent's workspace) and can't be
  enforced here.

Refund safety: each license doc records which entitlements it NEWLY granted,
so a deactivate (refund) removes only AppSumo's own grants — a Pinball
customer who also bought on AppSumo keeps their original purchases.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("f48.appsumo")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---------------------------------------------------------------------------
# Configuration — db.settings("appsumo") > env var > baked-in default.
# The baked-in webhook token exists because the owner can't edit env vars on
# her deployment platform: the webhook URL saved in the AppSumo Partner
# Portal must carry this exact token unless it's overridden in db/env.
# ---------------------------------------------------------------------------
DEFAULT_WEBHOOK_TOKEN = "as_06e0e0bb12f22e97c3335db2a344587fb0e3772a"

ENV_DEFAULTS = {
    "webhook_token": os.environ.get("APPSUMO_WEBHOOK_TOKEN", "").strip() or DEFAULT_WEBHOOK_TOKEN,
    "api_key": os.environ.get("APPSUMO_API_KEY", "").strip(),
    "client_id": os.environ.get("APPSUMO_CLIENT_ID", "").strip(),
    "client_secret": os.environ.get("APPSUMO_CLIENT_SECRET", "").strip(),
    "redirect_uri": os.environ.get(
        "APPSUMO_REDIRECT_URI", "https://faceless48.c3global.co/redeem"
    ).strip(),
}

APPSUMO_TOKEN_URL = "https://appsumo.com/openid/token/"
APPSUMO_LICENSE_URL = "https://appsumo.com/openid/license_key/"

# AppSumo tier number → entitlements granted. JSON env override so new tiers
# don't need a code change (same convention as PINBALL_PRODUCT_MAP).
DEFAULT_APPSUMO_TIER_MAP = {
    "1": ["base", "shorts"],
    "2": ["base", "shorts", "studio"],
    "3": ["base", "shorts", "studio"],
}
try:
    _env_map = os.environ.get("APPSUMO_TIER_MAP", "").strip()
    APPSUMO_TIER_MAP = json.loads(_env_map) if _env_map else DEFAULT_APPSUMO_TIER_MAP
except json.JSONDecodeError:
    logger.warning("APPSUMO_TIER_MAP env var is not valid JSON, falling back to defaults")
    APPSUMO_TIER_MAP = DEFAULT_APPSUMO_TIER_MAP

# Per-tier feature limits, enforced in server.py for AppSumo-sourced buyers.
# sprint: Content Sprint (5-variant shorts) allowed?
# faceless_per_month / avatar_per_month: Studio render quotas (0 = not included).
# Composite renders use a HeyGen avatar, so they draw from the avatar quota.
# JSON env override APPSUMO_TIER_LIMITS_MAP available for future tier changes.
DEFAULT_APPSUMO_TIER_LIMITS = {
    "1": {"sprint": False, "faceless_per_month": 0, "avatar_per_month": 0},
    "2": {"sprint": True, "faceless_per_month": 3, "avatar_per_month": 0},
    "3": {"sprint": True, "faceless_per_month": 10, "avatar_per_month": 3},
}
try:
    _env_limits = os.environ.get("APPSUMO_TIER_LIMITS_MAP", "").strip()
    APPSUMO_TIER_LIMITS = json.loads(_env_limits) if _env_limits else DEFAULT_APPSUMO_TIER_LIMITS
except json.JSONDecodeError:
    logger.warning("APPSUMO_TIER_LIMITS_MAP env var is not valid JSON, falling back to defaults")
    APPSUMO_TIER_LIMITS = DEFAULT_APPSUMO_TIER_LIMITS

STUDIO_LIFETIME_PERIOD_END = "2099-01-01T00:00:00Z"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_appsumo_config(db) -> dict:
    """Effective config: db.settings overrides env/defaults per field."""
    cfg = dict(ENV_DEFAULTS)
    doc = await db.settings.find_one({"_id": "appsumo"}) or {}
    for key in cfg:
        val = (doc.get(key) or "").strip() if isinstance(doc.get(key), str) else doc.get(key)
        if val:
            cfg[key] = val
    return cfg


def _tier_entitlements(tier: Any) -> list[str]:
    """Entitlements for an AppSumo tier. Unknown tiers fall back to tier 1
    (better to under-grant a brand-new tier than to drop the webhook)."""
    ents = APPSUMO_TIER_MAP.get(str(tier or 1))
    if ents is None:
        logger.warning(f"[appsumo] unknown tier {tier!r}; falling back to tier 1")
        ents = APPSUMO_TIER_MAP.get("1", ["base", "shorts"])
    return sorted(set(ents))


async def get_buyer_appsumo_limits(db, email: str) -> Optional[dict]:
    """Per-month feature limits for a buyer, or None for unlimited access.

    Limits apply only to pure AppSumo customers (buyer.source == "appsumo"
    with an appsumo_tier on file). Buyers who first arrived via Pinball /
    admin grant keep unrestricted access even if they also redeem an
    AppSumo license. Imported by server.py at the render + sprint gates.
    """
    buyer = await db.buyers.find_one({"email": (email or "").strip().lower()})
    if not buyer or buyer.get("source") != "appsumo":
        return None
    tier = buyer.get("appsumo_tier")
    if tier is None:
        return None
    limits = APPSUMO_TIER_LIMITS.get(str(tier))
    if limits is None:
        # Unknown tier — don't lock a paying customer out; log for follow-up.
        logger.warning(f"[appsumo] no limits defined for tier {tier!r} ({email})")
        return None
    return {**limits, "tier": tier}


def _verify_signature(api_key: str, raw_body: bytes, timestamp: str, signature: str) -> bool:
    """HMAC SHA256 of (timestamp + raw body) keyed with the Partner API key,
    hex-encoded, compared against X-Appsumo-Signature in constant time."""
    expected = hmac.new(
        api_key.encode("utf-8"),
        timestamp.encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected.lower(), (signature or "").strip().lower())


class RedeemPayload(BaseModel):
    code: str
    email: str


class AppsumoConfigPayload(BaseModel):
    # All optional — PUT accepts partial updates; empty string clears a field
    # back to its env/default value.
    webhook_token: Optional[str] = None
    api_key: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None


def _mask(secret: str) -> str:
    if not secret:
        return ""
    return f"…{secret[-4:]}" if len(secret) > 4 else "…"


def register_appsumo_routes(*, api, db, current_user, log_activity) -> None:
    """Attach the AppSumo webhook + OAuth redemption + admin config routes to
    the shared `api` FastAPI sub-app. Mirrors register_admin_routes' style."""
    from fastapi import Depends  # noqa: PLC0415 — keep module surface tiny

    # ------------------------------------------------------------------
    # Shared grant / revoke helpers
    # ------------------------------------------------------------------
    async def _active_tiers(email: str, exclude_key: Optional[str] = None) -> list[int]:
        """Tier numbers of the buyer's ACTIVE AppSumo licenses (parent deals
        only — add-ons carry a tier but don't map to plan tiers)."""
        filt: dict[str, Any] = {
            "email": email, "status": "active",
            "parent_license_key": {"$in": [None, ""]},
        }
        if exclude_key:
            filt["license_key"] = {"$ne": exclude_key}
        tiers = []
        async for other in db.appsumo_licenses.find(filt):
            try:
                tiers.append(int(other.get("tier") or 1))
            except (TypeError, ValueError):
                tiers.append(1)
        return tiers

    async def _grant_for_license(email: str, lic: dict) -> list[str]:
        """Grant the license's tier entitlements to `email` in db.buyers.
        Records which entitlements were newly added by THIS license on the
        license doc so a refund only claws back AppSumo's own grants.
        Returns the buyer's full entitlement list after the merge."""
        ents = _tier_entitlements(lic.get("tier"))
        buyer = await db.buyers.find_one({"email": email})
        prev = set((buyer.get("entitlements") if buyer else []) or [])
        newly = sorted(set(ents) - prev)
        merged = sorted(prev | set(ents))

        try:
            this_tier = int(lic.get("tier") or 1)
        except (TypeError, ValueError):
            this_tier = 1
        # Highest tier across active licenses wins (covers upgrade windows
        # where old + new keys are briefly both active).
        tier = max([this_tier, *(await _active_tiers(email, exclude_key=lic["license_key"]))])

        set_doc: dict[str, Any] = {
            "email": email,
            "entitlements": merged,
            "appsumo_tier": tier,
            "updatedAt": _now_iso(),
            "source": "appsumo" if not buyer else (buyer.get("source") or "appsumo"),
        }
        if "studio" in ents:
            set_doc["studio_status"] = "active"
            set_doc["studio_lifetime"] = True
            set_doc["studio_current_period_end"] = STUDIO_LIFETIME_PERIOD_END
        if newly:
            set_doc["pending_welcome"] = True
            set_doc["pending_welcome_ents"] = newly
        update: dict[str, Any] = {
            "$set": set_doc,
            "$addToSet": {"appsumo_license_keys": lic["license_key"]},
        }
        if not buyer:
            update["$setOnInsert"] = {"addedAt": _now_iso()}
        await db.buyers.update_one({"email": email}, update, upsert=True)

        await db.appsumo_licenses.update_one(
            {"license_key": lic["license_key"]},
            {"$set": {"email": email, "granted_entitlements": newly, "updatedAt": _now_iso()}},
        )
        return merged

    async def _revoke_for_license(lic: dict) -> list[str]:
        """Claw back what THIS license granted, but keep any entitlement still
        covered by another active AppSumo license on the same email (upgrade
        flows: the new key's grant must survive the old key's deactivate).
        Also recomputes the buyer's appsumo_tier from remaining licenses."""
        email = lic.get("email")
        if not email:
            return []
        buyer = await db.buyers.find_one({"email": email})
        if not buyer:
            return []
        remaining_tiers = await _active_tiers(email, exclude_key=lic["license_key"])
        removable = set(lic.get("granted_entitlements") or [])
        keep: set[str] = set()
        for t in remaining_tiers:
            keep |= set(_tier_entitlements(t))
        to_remove = sorted(removable - keep)

        update: dict[str, Any] = {
            "$set": {"updatedAt": _now_iso()},
            "$pull": {"appsumo_license_keys": lic["license_key"]},
        }
        if remaining_tiers:
            update["$set"]["appsumo_tier"] = max(remaining_tiers)
        else:
            update.setdefault("$unset", {})["appsumo_tier"] = ""
        if to_remove:
            remaining_ents = sorted(set(buyer.get("entitlements") or []) - set(to_remove))
            update["$set"]["entitlements"] = remaining_ents
            if "studio" in to_remove:
                update.setdefault("$unset", {}).update(
                    {"studio_status": "", "studio_lifetime": "", "studio_current_period_end": ""}
                )
        await db.buyers.update_one({"email": email}, update)
        return to_remove

    # ------------------------------------------------------------------
    # Webhook receiver
    # ------------------------------------------------------------------
    @api.post("/appsumo-webhook")
    async def appsumo_webhook(request: Request, token: str = Query(...)):
        cfg = await get_appsumo_config(db)

        # 1) Token gate.
        if not cfg["webhook_token"] or not hmac.compare_digest(token, cfg["webhook_token"]):
            await log_activity(
                "webhook_failed",
                "",
                {"reason": "invalid token", "source": "appsumo"},
            )
            raise HTTPException(status_code=401, detail="Invalid token")

        raw = await request.body()

        # 2) Optional HMAC verification (enabled once the API key is set).
        if cfg["api_key"]:
            ts = request.headers.get("X-Appsumo-Timestamp", "")
            sig = request.headers.get("X-Appsumo-Signature", "")
            if not _verify_signature(cfg["api_key"], raw, ts, sig):
                await log_activity(
                    "webhook_failed",
                    "",
                    {"reason": "invalid HMAC signature", "source": "appsumo"},
                )
                raise HTTPException(status_code=401, detail="Invalid signature")

        # 3) Parse — AppSumo ships JSON or form-encoded.
        body: dict = {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            try:
                form = await request.form()
                body = dict(form)
            except Exception:
                body = {}
        if not isinstance(body, dict) or not body.get("event") or not body.get("license_key"):
            await log_activity(
                "webhook_failed",
                "",
                {"reason": "malformed payload", "source": "appsumo",
                 "payload": raw.decode("utf-8", "replace")[:1000]},
            )
            raise HTTPException(status_code=400, detail="Malformed payload")

        event = str(body["event"]).strip().lower()
        license_key = str(body["license_key"]).strip()
        is_test = bool(body.get("test"))

        # 4) Partner Portal validation pings — acknowledge, change nothing.
        if is_test:
            await log_activity(
                "webhook", "",
                {"status": "test", "event": event, "license_key": license_key, "source": "appsumo"},
            )
            return {"event": event, "success": True}

        # 5) Upsert the license doc. AppSumo is the source of truth for keys;
        #    we keep a durable, support-searchable mirror.
        base_fields = {
            "license_key": license_key,
            "tier": body.get("tier"),
            "last_event": event,
            "last_event_timestamp": body.get("event_timestamp"),
            "appsumo_created_at": body.get("created_at"),
            "partner_plan_name": body.get("partner_plan_name"),
            "unit_quantity": body.get("unit_quantity"),
            "parent_license_key": body.get("parent_license_key"),
            "extra": body.get("extra"),
            "updatedAt": _now_iso(),
        }
        # Drop Nones so a sparse payload (e.g. deactivate has no tier) never
        # erases fields learned from earlier events.
        base_fields = {k: v for k, v in base_fields.items() if v is not None}

        detail: dict[str, Any] = {
            "status": "ok", "event": event, "license_key": license_key, "source": "appsumo",
        }

        if event == "purchase":
            await db.appsumo_licenses.update_one(
                {"license_key": license_key},
                {"$set": {**base_fields, "status": "purchased"},
                 "$setOnInsert": {"addedAt": _now_iso()}},
                upsert=True,
            )

        elif event == "activate":
            # license_status arrives "inactive" by design — AppSumo flips it
            # to active only after we return 200.
            await db.appsumo_licenses.update_one(
                {"license_key": license_key},
                {"$set": {**base_fields, "status": "active", "activated_at": _now_iso()},
                 "$setOnInsert": {"addedAt": _now_iso()}},
                upsert=True,
            )
            lic = await db.appsumo_licenses.find_one({"license_key": license_key})
            if lic and lic.get("email"):
                ents = await _grant_for_license(lic["email"], lic)
                detail["email"] = lic["email"]
                detail["entitlements"] = ents

        elif event in ("upgrade", "downgrade"):
            # New key is always issued; the old key gets its own simultaneous
            # deactivate event. Carry the email link over via prev_license_key.
            prev_key = str(body.get("prev_license_key") or "").strip()
            email: Optional[str] = None
            if prev_key:
                old = await db.appsumo_licenses.find_one({"license_key": prev_key})
                if old:
                    email = old.get("email")
            update = {"$set": {**base_fields, "status": "active",
                               "prev_license_key": prev_key or None},
                      "$setOnInsert": {"addedAt": _now_iso()}}
            if email:
                update["$set"]["email"] = email
            update["$set"] = {k: v for k, v in update["$set"].items() if v is not None}
            await db.appsumo_licenses.update_one(
                {"license_key": license_key}, update, upsert=True
            )
            if email:
                lic = await db.appsumo_licenses.find_one({"license_key": license_key})
                ents = await _grant_for_license(email, lic)
                detail["email"] = email
                detail["entitlements"] = ents

        elif event == "deactivate":
            # license_status arrives "active" by design — AppSumo deactivates
            # after we return 200. Refunds/cancellations land here.
            lic = await db.appsumo_licenses.find_one({"license_key": license_key})
            await db.appsumo_licenses.update_one(
                {"license_key": license_key},
                {"$set": {**base_fields, "status": "deactivated", "deactivated_at": _now_iso()},
                 "$setOnInsert": {"addedAt": _now_iso()}},
                upsert=True,
            )
            if lic:
                removed = await _revoke_for_license(lic)
                if removed:
                    detail["email"] = lic.get("email")
                    detail["revoked"] = removed

        elif event == "migrate":
            # Add-on follows its parent deal's upgrade/downgrade: the add-on's
            # own key is stable, only parent_license_key changes.
            await db.appsumo_licenses.update_one(
                {"license_key": license_key},
                {"$set": base_fields, "$setOnInsert": {"addedAt": _now_iso(), "status": "active"}},
                upsert=True,
            )

        else:
            # Unknown event type — record it and still ACK so AppSumo doesn't
            # retry forever; the activity log surfaces it for investigation.
            detail["status"] = "unknown_event"
            await db.appsumo_licenses.update_one(
                {"license_key": license_key},
                {"$set": base_fields, "$setOnInsert": {"addedAt": _now_iso()}},
                upsert=True,
            )

        await log_activity("webhook", detail.get("email") or "", detail)
        return {"event": event, "success": True}

    # ------------------------------------------------------------------
    # OAuth redemption — called by the /redeem page with ?code= from AppSumo
    # ------------------------------------------------------------------
    @api.post("/appsumo/redeem")
    async def appsumo_redeem(payload: RedeemPayload):
        email = payload.email.strip().lower()
        code = payload.code.strip()
        if not EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="Enter a valid email address.")
        if not code:
            raise HTTPException(status_code=400, detail="Missing AppSumo code. Please restart activation from AppSumo.")
        cfg = await get_appsumo_config(db)
        if not cfg["client_id"] or not cfg["client_secret"]:
            raise HTTPException(
                status_code=503,
                detail="AppSumo activation isn't configured yet. Please contact support@c3global.co.",
            )

        # Exchange the single-use code for an access token, then the token
        # for the buyer's license_key.
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            tr = await client.post(
                APPSUMO_TOKEN_URL,
                data={
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "redirect_uri": cfg["redirect_uri"],
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            if tr.status_code != 200:
                logger.warning(f"[appsumo] token exchange failed {tr.status_code}: {tr.text[:300]}")
                await log_activity(
                    "appsumo_redeem_failed", email,
                    {"reason": "token exchange failed", "status": tr.status_code},
                )
                raise HTTPException(
                    status_code=400,
                    detail="AppSumo code expired or already used. Please restart activation from your AppSumo account.",
                )
            access_token = (tr.json() or {}).get("access_token")
            if not access_token:
                raise HTTPException(status_code=502, detail="AppSumo did not return an access token. Please try again.")

            lr = await client.get(APPSUMO_LICENSE_URL, params={"access_token": access_token})
            if lr.status_code != 200:
                logger.warning(f"[appsumo] license fetch failed {lr.status_code}: {lr.text[:300]}")
                raise HTTPException(status_code=502, detail="Could not fetch your AppSumo license. Please try again.")
            lic_resp = lr.json() or {}

        license_key = (lic_resp.get("license_key") or "").strip()
        license_status = (lic_resp.get("status") or "").strip().lower()
        if not license_key:
            raise HTTPException(status_code=502, detail="AppSumo did not return a license key. Please try again.")
        if license_status == "deactivated":
            raise HTTPException(
                status_code=410,
                detail="This AppSumo license is no longer active. Contact AppSumo support if you believe this is an error.",
            )

        lic = await db.appsumo_licenses.find_one({"license_key": license_key})
        if lic and lic.get("email") and lic["email"] != email:
            await log_activity(
                "appsumo_redeem_failed", email,
                {"reason": "license already linked to another email", "license_key": license_key},
            )
            raise HTTPException(
                status_code=409,
                detail="This AppSumo license is already linked to a different email. Sign in with that email or contact support@c3global.co.",
            )
        if not lic:
            # Webhook may not have landed yet (or arrived out of order) —
            # create the record now; the webhook upsert will enrich it later.
            await db.appsumo_licenses.update_one(
                {"license_key": license_key},
                {"$set": {"license_key": license_key, "status": "active",
                          "last_event": "redeem", "updatedAt": _now_iso()},
                 "$setOnInsert": {"addedAt": _now_iso()}},
                upsert=True,
            )
            lic = await db.appsumo_licenses.find_one({"license_key": license_key})

        ents = await _grant_for_license(email, lic)

        # Link any add-ons of this deal to the same email so future add-on
        # events resolve to a buyer.
        await db.appsumo_licenses.update_many(
            {"parent_license_key": license_key},
            {"$set": {"email": email, "updatedAt": _now_iso()}},
        )

        await log_activity(
            "appsumo_redeem", email,
            {"status": "ok", "license_key": license_key, "entitlements": ents},
        )
        return {"ok": True, "email": email, "entitlements": ents}

    # ------------------------------------------------------------------
    # Admin — support-searchable license lookup (AppSumo partner requirement)
    # ------------------------------------------------------------------
    @api.get("/admin/appsumo/licenses")
    async def admin_appsumo_licenses(
        q: str = Query(default="", description="license_key or email substring"),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=50, ge=1, le=200),
        user=Depends(current_user),
    ):
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin only")
        filt: dict[str, Any] = {}
        if q.strip():
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            filt = {"$or": [{"license_key": rx}, {"email": rx}]}
        total = await db.appsumo_licenses.count_documents(filt)
        cursor = (
            db.appsumo_licenses.find(filt, {"_id": 0})
            .sort("updatedAt", -1)
            .skip((page - 1) * limit)
            .limit(limit)
        )
        items = [doc async for doc in cursor]
        return {"items": items, "total": total, "page": page, "limit": limit}

    # ------------------------------------------------------------------
    # Admin — AppSumo settings (db-backed, replaces env vars the owner
    # can't edit on her deployment platform)
    # ------------------------------------------------------------------
    @api.get("/admin/appsumo/config")
    async def admin_appsumo_config_get(user=Depends(current_user)):
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin only")
        cfg = await get_appsumo_config(db)
        return {
            # Full webhook token so the admin can copy the exact URL into
            # the AppSumo Partner Portal; real secrets stay masked.
            "webhook_token": cfg["webhook_token"],
            "webhook_url": f"https://faceless48.c3global.co/api/appsumo-webhook?token={cfg['webhook_token']}",
            "redirect_uri": cfg["redirect_uri"],
            "api_key_set": bool(cfg["api_key"]),
            "api_key_masked": _mask(cfg["api_key"]),
            "client_id_set": bool(cfg["client_id"]),
            "client_id_masked": _mask(cfg["client_id"]),
            "client_secret_set": bool(cfg["client_secret"]),
            "client_secret_masked": _mask(cfg["client_secret"]),
        }

    @api.put("/admin/appsumo/config")
    async def admin_appsumo_config_put(payload: AppsumoConfigPayload, user=Depends(current_user)):
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin only")
        updates = {
            k: v.strip()
            for k, v in payload.model_dump().items()
            if v is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")
        # Empty string clears the override (falls back to env/default);
        # store as unset so get_appsumo_config's truthiness check skips it.
        set_doc = {k: v for k, v in updates.items() if v}
        unset_doc = {k: "" for k, v in updates.items() if not v}
        update: dict[str, Any] = {}
        if set_doc:
            update["$set"] = {**set_doc, "updatedAt": _now_iso()}
        if unset_doc:
            update["$unset"] = unset_doc
        await db.settings.update_one({"_id": "appsumo"}, update, upsert=True)
        await log_activity(
            "appsumo_config_updated", user.email,
            {"fields": sorted(updates.keys())},  # names only — never log values
        )
        return await admin_appsumo_config_get(user)
