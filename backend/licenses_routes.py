"""License code redemption + bulk provisioning + tier upgrades.

This module powers the AppSumo launch (and any future code-based acquisition
channel — partner codes, agency reseller codes, beta codes). Crucially, the
CUSTOMER-FACING surface never says "AppSumo": the /redeem page accepts any
code regardless of source, and admin reporting separates codes by their
`source` field for the operator's eyes only.

Schema:
    db.redemption_codes:
        _id:         the code string (uppercased, dashes preserved)
        tier:        "t1" | "t2" | "t3"  (Founder is intentionally
                     NOT redeemable — see tier_config.REDEEMABLE_TIER_IDS)
        source:      "appsumo" | "partner" | "beta" | "manual" | …
        status:      "available" | "redeemed" | "void"
        batch_id:    optional, set by bulk import for admin filtering
        notes:       free-form admin note
        created_at:  ISO timestamp
        redeemed_by: email (None until redeemed)
        redeemed_at: ISO timestamp (None until redeemed)

Endpoints exposed:
    POST   /api/licenses/redeem                — customer-facing
    GET    /api/me/upgrade-target              — customer-facing
    POST   /api/admin/licenses/bulk-create     — admin only
    GET    /api/admin/licenses                  — admin only
    POST   /api/admin/licenses/{code}/void     — admin only
    POST   /api/admin/buyers/{email}/upgrade-tier — admin only
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from tier_config import (
    REDEEMABLE_TIER_IDS, TIERS_ORDERED, assign_buyer_to_tier, get_tier,
)


logger = logging.getLogger("licenses")


# Codes are normalized at the boundary: uppercased + whitespace stripped, but
# dashes / underscores preserved (AppSumo's default format uses dashes and
# customers paste them verbatim from email). This keeps lookups deterministic
# while accepting any format AppSumo (or partners) generate.
_CODE_NORMALIZE_RE = re.compile(r"\s+")


def _normalize_code(code: str) -> str:
    if not code:
        return ""
    return _CODE_NORMALIZE_RE.sub("", code).strip().upper()


def _is_plausible_code(code: str) -> bool:
    """Loose validation — we accept ANY format AppSumo generates so we don't
    have to refactor when they change. Reject only obviously broken input
    (empty, too short, too long, control chars)."""
    if not code or len(code) < 6 or len(code) > 64:
        return False
    # Allow alphanumerics, dashes, underscores. Block whitespace + symbols.
    return bool(re.fullmatch(r"[A-Z0-9\-_]+", code))


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=128)


class BulkCreateRequest(BaseModel):
    """Two intake formats supported simultaneously:
      1. `codes`: explicit list of {code, tier, notes?} dicts (programmatic).
      2. `csv`: paste of a CSV blob with columns code,tier[,notes] — friendly
         for admins importing AppSumo's CSV export.
    Exactly one of the two must be provided per request.
    """
    codes: Optional[list[dict]] = None
    csv: Optional[str] = None
    source: str = Field(default="appsumo", max_length=32)
    batch_id: Optional[str] = Field(default=None, max_length=64)


class UpgradeTierRequest(BaseModel):
    tier: str = Field(..., min_length=1, max_length=16)


def _campaign_active_now() -> bool:
    """True if we're currently inside the AppSumo campaign window. Controlled
    by the APPSUMO_CAMPAIGN_END_AT env var (ISO date). If unset OR malformed,
    we default to FALSE so the upgrade button quietly hides instead of
    pointing somewhere wrong."""
    end_at = (os.environ.get("APPSUMO_CAMPAIGN_END_AT") or "").strip()
    if not end_at:
        return False
    try:
        # Accept "2026-09-01" or full ISO. Treat as end-of-day UTC.
        if "T" not in end_at:
            end_at = end_at + "T23:59:59+00:00"
        end = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) <= end
    except Exception:
        logger.warning("Bad APPSUMO_CAMPAIGN_END_AT value: %r", end_at)
        return False


# =============================================================================
# AppSumo Licensing v2 — OAuth exchange + license-key redemption (2026-07-02)
#
# AppSumo buyers arrive with either:
#   (a) their license_key UUID pasted from AppSumo → My Products / the
#       confirmation email ("License key redemption" flow), or
#   (b) a single-use OAuth ?code= on the redirect URL, which must be
#       exchanged at appsumo.com/openid/token/ for the license_key.
# Neither exists in db.redemption_codes (that inventory is for partner /
# beta / manual codes), so redemption falls through to db.appsumo_licenses —
# the collection the /api/appsumo-webhook handler populates on `purchase`.
#
# These helpers are MODULE-LEVEL (not closures) because the magic-link
# verify flow in server.py also needs them: a brand-new AppSumo buyer has no
# buyer record, so redemption must run inside sign-in, right after email
# ownership is proven.
# =============================================================================

APPSUMO_TOKEN_URL = "https://appsumo.com/openid/token/"
APPSUMO_LICENSE_URL = "https://appsumo.com/openid/license_key/"

# Marker prefix for OAuth codes riding through the shared redemption path
# (they must keep their original case, unlike inventory codes).
OAUTH_CODE_PREFIX = "oauth:"


async def get_appsumo_oauth_config(db) -> dict:
    """OAuth client credentials: db.settings("appsumo") overrides env vars.
    The db layer exists because the operator can't edit env vars on her
    deployment platform — credentials are pasted via the admin config
    endpoint instead."""
    cfg = {
        "client_id": (os.environ.get("APPSUMO_CLIENT_ID") or "").strip(),
        "client_secret": (os.environ.get("APPSUMO_CLIENT_SECRET") or "").strip(),
        "redirect_uri": (os.environ.get("APPSUMO_REDIRECT_URI")
                         or "https://faceless48.c3global.co/redeem").strip(),
    }
    doc = await db.settings.find_one({"_id": "appsumo"}) or {}
    for key in cfg:
        val = doc.get(key)
        if isinstance(val, str) and val.strip():
            cfg[key] = val.strip()
    return cfg


async def exchange_appsumo_oauth_code(db, oauth_code: str) -> dict:
    """Exchange a single-use AppSumo OAuth code for the buyer's license.
    Returns {"license_key": ..., "status": ...}. Raises HTTPException with
    customer-friendly copy on every failure mode."""
    import httpx  # noqa: PLC0415 — keep module import surface light

    cfg = await get_appsumo_oauth_config(db)
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(
            status_code=503,
            detail="AppSumo activation isn't fully configured yet. Please contact support@c3global.co.",
        )
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        tr = await client.post(
            APPSUMO_TOKEN_URL,
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": cfg["redirect_uri"],
                "code": oauth_code,
                "grant_type": "authorization_code",
            },
        )
        if tr.status_code != 200:
            logger.warning("[appsumo] token exchange failed %s: %s",
                           tr.status_code, tr.text[:300])
            raise HTTPException(
                status_code=400,
                detail="Your AppSumo activation link expired or was already used. Please restart activation from AppSumo → My Products.",
            )
        access_token = (tr.json() or {}).get("access_token")
        if not access_token:
            raise HTTPException(status_code=502,
                                detail="AppSumo didn't return an access token. Please try again.")
        lr = await client.get(APPSUMO_LICENSE_URL, params={"access_token": access_token})
        if lr.status_code != 200:
            logger.warning("[appsumo] license fetch failed %s: %s",
                           lr.status_code, lr.text[:300])
            raise HTTPException(status_code=502,
                                detail="We couldn't fetch your AppSumo license. Please try again.")
        data = lr.json() or {}
    license_key = (data.get("license_key") or "").strip()
    if not license_key:
        raise HTTPException(status_code=502,
                            detail="AppSumo didn't return a license key. Please try again.")
    return {"license_key": license_key, "status": (data.get("status") or "").strip().lower()}


async def _apply_tier_to_buyer(
    db, *, email: str, tier_id: str, source: str, code_ref: str,
    dev_bypass_email: str, studio_grant_emails: set,
) -> None:
    """Shared buyer-provisioning core: protected-account guard + strictly-
    higher tier bump via assign_buyer_to_tier. Mirrors the inventory-code
    endpoint's rules (locked 2026-06-29): founders / dev-bypass / studio-
    grant emails are never demoted; downgrades via redemption are skipped."""
    buyer = await db.buyers.find_one({"email": email})
    now_iso = _iso_now()
    is_protected = (
        (dev_bypass_email and email == dev_bypass_email)
        or email in studio_grant_emails
        or bool((buyer or {}).get("founders"))
    )
    if is_protected:
        return
    current_tier_id = ((buyer or {}).get("tier") or "").strip().lower()
    is_first_time = not current_tier_id or current_tier_id not in REDEEMABLE_TIER_IDS
    if _tier_rank(tier_id) <= _tier_rank(current_tier_id):
        logger.info(
            "[licenses] redeem skipped tier bump: user=%s current=%s code_tier=%s code=%s",
            email, current_tier_id, tier_id, code_ref,
        )
        return
    tier_fields = assign_buyer_to_tier(tier_id=tier_id, is_upgrade=not is_first_time)
    tier_fields.setdefault("source", source)
    tier_fields.setdefault("orderId", code_ref)
    tier_fields["lastRedeemedCode"] = code_ref
    tier_fields["updatedAt"] = now_iso
    if is_first_time:
        tier_fields.setdefault("addedAt", now_iso)
        tier_fields.setdefault("firstUseAt", now_iso)
    await db.buyers.update_one(
        {"email": email},
        {"$set": tier_fields, "$setOnInsert": {"email": email, "founders": False}},
        upsert=True,
    )


def _push_ghl_redeemed(email: str, tier_id: str, code: str, metadata: dict, log_activity) -> None:
    """Fire-and-forget GHL onboarding push (tier sequence + source tag)."""
    try:
        import ghl_integration  # local import keeps the routes module light
        if ghl_integration.is_configured():
            ghl_payload = ghl_integration.build_payload(
                email=email,
                tier_id=tier_id,
                tier_label=get_tier(tier_id).label,
                source="appsumo_redemption",
                founder=False,
                metadata=metadata,
            )
            ghl_integration.push_in_background(ghl_payload, log_activity=log_activity)
    except Exception as exc:
        logger.warning("[ghl] redeem push wiring failed: %s: %s", type(exc).__name__, exc)


async def _redeem_appsumo_license_key(
    db, *, email: str, code: str, log_activity,
    dev_bypass_email: str, studio_grant_emails: set,
) -> Optional[dict]:
    """License-key redemption against db.appsumo_licenses (webhook-populated).
    Returns None when the key is unknown (caller falls through to its 404),
    a success dict when redeemed, or raises HTTPException on conflicts."""
    lic = await db.appsumo_licenses.find_one({
        "license_key": {"$regex": f"^{re.escape(code)}$", "$options": "i"},
    })
    if not lic:
        return None
    if (lic.get("license_status") or "").lower() == "deactivated" or \
            (lic.get("last_event") or "").lower() in ("deactivate", "refund"):
        raise HTTPException(
            status_code=410,
            detail="This AppSumo license is no longer active. Contact AppSumo support if you believe this is an error.",
        )
    linked = (lic.get("email") or "").strip().lower()
    if linked and linked != email:
        raise HTTPException(
            status_code=409,
            detail="This AppSumo license is already linked to a different email. Sign in with that email or contact support@c3global.co.",
        )

    from tier_config import appsumo_tier_to_tier_id  # noqa: PLC0415
    tier_id = appsumo_tier_to_tier_id(lic.get("tier"))
    if not tier_id:
        # Webhook hasn't told us the tier (or shipped something unmappable).
        # Provision at the lowest paid tier rather than blocking the buyer;
        # the activity log flags it for admin follow-up / manual bump.
        logger.warning("[appsumo] license %s has unmappable tier %r — provisioning t1",
                       lic.get("license_key"), lic.get("tier"))
        tier_id = "t1"

    await _apply_tier_to_buyer(
        db, email=email, tier_id=tier_id, source="appsumo",
        code_ref=lic["license_key"], dev_bypass_email=dev_bypass_email,
        studio_grant_emails=studio_grant_emails,
    )
    await db.appsumo_licenses.update_one(
        {"license_key": lic["license_key"]},
        {"$set": {"email": email, "redeemed_at": _iso_now(), "updated_at": _iso_now()}},
    )
    await log_activity("license_redeemed", email, {
        "code": lic["license_key"], "tier": tier_id, "source": "appsumo_license",
    })
    _push_ghl_redeemed(email, tier_id, lic["license_key"],
                       {"license_key": lic["license_key"], "license_source": "appsumo"},
                       log_activity)
    return {
        "ok": True,
        "tier": tier_id,
        "tier_label": get_tier(tier_id).label,
        "message": f"Welcome — you're on {get_tier(tier_id).label}.",
    }


async def redeem_for_email(
    db, *, email: str, code_raw: str, log_activity,
    dev_bypass_email: str = "", studio_grant_emails: Optional[set] = None,
) -> dict:
    """Single entry point for every redemption path. Accepts:
      • an inventory code (db.redemption_codes — partner/beta/manual),
      • an AppSumo license key (db.appsumo_licenses — webhook-populated),
      • `oauth:<code>` — AppSumo OAuth redirect code, exchanged first.
    Called by POST /api/licenses/redeem (signed-in flow) AND by the
    magic-link verify flow in server.py (new-buyer onboarding)."""
    studio_grant_emails = studio_grant_emails or set()
    email = (email or "").strip().lower()
    code_raw = (code_raw or "").strip()

    # OAuth path — exchange first (case-sensitive code), then treat the
    # returned license_key exactly like a pasted one.
    if code_raw.lower().startswith(OAUTH_CODE_PREFIX):
        oauth_code = code_raw[len(OAUTH_CODE_PREFIX):].strip()
        if not oauth_code:
            raise HTTPException(status_code=400, detail="Missing AppSumo activation code.")
        exchanged = await exchange_appsumo_oauth_code(db, oauth_code)
        if exchanged["status"] == "deactivated":
            raise HTTPException(
                status_code=410,
                detail="This AppSumo license is no longer active. Contact AppSumo support if you believe this is an error.",
            )
        license_key = exchanged["license_key"]
        # The purchase webhook usually landed first; if not (out-of-order
        # delivery), create the license record now so redemption works and
        # the webhook enriches it (incl. tier) when it arrives.
        await db.appsumo_licenses.update_one(
            {"license_key": license_key},
            {"$setOnInsert": {"license_key": license_key, "created_at": _iso_now(),
                              "source": "oauth"},
             "$set": {"license_status": exchanged["status"] or "active",
                      "updated_at": _iso_now()}},
            upsert=True,
        )
        result = await _redeem_appsumo_license_key(
            db, email=email, code=license_key, log_activity=log_activity,
            dev_bypass_email=dev_bypass_email, studio_grant_emails=studio_grant_emails,
        )
        # Can't be None — we just upserted the license row.
        return result or {"ok": False}

    code = _normalize_code(code_raw)
    if not _is_plausible_code(code):
        raise HTTPException(
            status_code=400,
            detail="That doesn't look like a valid code. Double-check the email it came in.",
        )

    record = await db.redemption_codes.find_one({"_id": code})
    if not record:
        # Not an inventory code — try the AppSumo license-key path before
        # giving up (buyers paste their license key from AppSumo → My
        # Products, which is never pre-loaded into redemption_codes).
        appsumo_result = await _redeem_appsumo_license_key(
            db, email=email, code=code, log_activity=log_activity,
            dev_bypass_email=dev_bypass_email, studio_grant_emails=studio_grant_emails,
        )
        if appsumo_result is not None:
            return appsumo_result
        # Don't reveal that the code DOESN'T exist (helps prevent
        # enumeration attacks against the code namespace). Same copy
        # as "void" / "expired".
        raise HTTPException(
            status_code=404,
            detail="That code isn't valid or has already been used. Contact support if you think this is a mistake.",
        )
    if record.get("status") == "void":
        raise HTTPException(
            status_code=410,
            detail="That code has been voided. Please contact support.",
        )
    if record.get("status") == "redeemed":
        # If the SAME user is re-redeeming (e.g. they clicked twice),
        # treat as a no-op success so the UI doesn't error. Otherwise
        # surface a friendly "already used" message.
        if (record.get("redeemed_by") or "").lower() == email:
            return {
                "ok": True,
                "already_redeemed": True,
                "tier": record.get("tier"),
                "message": "You've already redeemed this code.",
            }
        raise HTTPException(
            status_code=409,
            detail="That code has already been used. If you bought multiple, check your inbox for the other codes.",
        )

    tier_id = (record.get("tier") or "").strip().lower()
    if tier_id not in REDEEMABLE_TIER_IDS:
        logger.error("Code %s has non-redeemable tier %r — voiding.", code, tier_id)
        await db.redemption_codes.update_one(
            {"_id": code}, {"$set": {"status": "void", "voided_at": _iso_now()}}
        )
        raise HTTPException(
            status_code=500,
            detail="That code is misconfigured. Please contact support so we can replace it.",
        )

    await _apply_tier_to_buyer(
        db, email=email, tier_id=tier_id,
        source=record.get("source") or "appsumo", code_ref=code,
        dev_bypass_email=dev_bypass_email, studio_grant_emails=studio_grant_emails,
    )

    # Atomic flip on the code record so two concurrent redeems can't both
    # win the race. The status filter `available` is the race lock.
    flipped = await db.redemption_codes.find_one_and_update(
        {"_id": code, "status": "available"},
        {"$set": {
            "status": "redeemed",
            "redeemed_by": email,
            "redeemed_at": _iso_now(),
        }},
        return_document=True,
    )
    if not flipped:
        # Another concurrent redeem won the race. Surface as 409 so the
        # UI shows the same "already used" copy without leaking state.
        raise HTTPException(
            status_code=409,
            detail="That code has already been used. If you bought multiple, check your inbox for the other codes.",
        )

    await log_activity("license_redeemed", email, {
        "code": code,
        "tier": tier_id,
        "source": record.get("source"),
        "batch_id": record.get("batch_id"),
    })
    _push_ghl_redeemed(email, tier_id, code,
                       {"code": code, "batch_id": record.get("batch_id"),
                        "license_source": record.get("source")},
                       log_activity)

    return {
        "ok": True,
        "tier": tier_id,
        "tier_label": get_tier(tier_id).label,
        "message": f"Welcome — you're on {get_tier(tier_id).label}.",
    }


def register_license_routes(
    *,
    api: APIRouter,
    db,
    current_user_dep,
    require_admin_dep,
    log_activity,
    dev_bypass_email: str,
    studio_grant_emails: set,
):
    """Mount license + upgrade-target routes on the /api router."""

    # =====================================================================
    # Customer-facing
    # =====================================================================

    @api.post("/licenses/redeem")
    async def redeem(payload: RedeemRequest, user=Depends(current_user_dep)):
        """Apply a redemption code to the signed-in user's buyer record.

        Idempotent on the code side: once a code's status flips to "redeemed"
        a second redeem-attempt returns 410 with the original redeemer email
        so customer-support can tell whether a friend already burned the
        code. Tier bumps are applied via `assign_buyer_to_tier(is_upgrade=…)`
        which keeps the existing cycle clock when upgrading mid-cycle (the
        rule we locked with the user on 2026-06-29).

        Accepts inventory codes AND AppSumo license keys — the shared
        redeem_for_email helper falls through to db.appsumo_licenses when
        the code isn't in the redemption_codes inventory."""
        return await redeem_for_email(
            db, email=user.email, code_raw=payload.code, log_activity=log_activity,
            dev_bypass_email=dev_bypass_email, studio_grant_emails=studio_grant_emails,
        )

    @api.post("/licenses/redeem-oauth")
    async def redeem_oauth(payload: RedeemRequest, user=Depends(current_user_dep)):
        """AppSumo OAuth activation for signed-in users. The /redeem page
        calls this with the `?code=` / `?appsumo_code=` query param AppSumo
        appends on its redirect; we exchange it for the license key and
        provision the tier. New buyers (not signed in yet) go through the
        magic-link flow instead, which replays the same helper."""
        return await redeem_for_email(
            db, email=user.email,
            code_raw=f"{OAUTH_CODE_PREFIX}{payload.code.strip()}",
            log_activity=log_activity,
            dev_bypass_email=dev_bypass_email, studio_grant_emails=studio_grant_emails,
        )

    # =====================================================================
    # Admin — AppSumo OAuth credentials (db-backed; the operator can't edit
    # env vars on her deployment platform, so client_id / client_secret
    # from the Partner Portal are pasted here after URL validation).
    # =====================================================================

    @api.get("/admin/appsumo/config")
    async def admin_appsumo_config_get(admin=Depends(require_admin_dep)):
        cfg = await get_appsumo_oauth_config(db)

        def _mask(v: str) -> str:
            return (f"…{v[-4:]}" if len(v) > 4 else "…") if v else ""

        return {
            "redirect_uri": cfg["redirect_uri"],
            "client_id_set": bool(cfg["client_id"]),
            "client_id_masked": _mask(cfg["client_id"]),
            "client_secret_set": bool(cfg["client_secret"]),
            "client_secret_masked": _mask(cfg["client_secret"]),
        }

    @api.put("/admin/appsumo/config")
    async def admin_appsumo_config_put(
        payload: dict = Body(default_factory=dict),
        admin=Depends(require_admin_dep),
    ):
        allowed = {"client_id", "client_secret", "redirect_uri"}
        updates = {
            k: str(v).strip()
            for k, v in (payload or {}).items()
            if k in allowed and v is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail="Nothing to update")
        set_doc = {k: v for k, v in updates.items() if v}
        unset_doc = {k: "" for k, v in updates.items() if not v}
        update: dict = {}
        if set_doc:
            update["$set"] = {**set_doc, "updatedAt": _iso_now()}
        if unset_doc:
            update["$unset"] = unset_doc
        await db.settings.update_one({"_id": "appsumo"}, update, upsert=True)
        await log_activity(
            "appsumo_config_updated", admin.email,
            {"fields": sorted(updates.keys())},  # names only — never log values
        )
        return await admin_appsumo_config_get(admin)

    @api.get("/me/upgrade-target")
    async def upgrade_target(user=Depends(current_user_dep)):
        """Returns where the in-app Upgrade button should send the user.

        Three states:
          1. Customer is at top tier / Founder / unlimited bucket → no
             upgrade visible (`visible: False`).
          2. Inside AppSumo campaign window (APPSUMO_CAMPAIGN_END_AT) and
             APPSUMO_STACK_URL set → link to AppSumo stack page, labeled
             "Stack codes on AppSumo".
          3. Post-campaign OR no AppSumo URL → link to OWN_PRICING_URL,
             labeled "Upgrade your plan". If OWN_PRICING_URL is also unset,
             we return `visible: False` so the button quietly hides instead
             of pointing somewhere broken.
        """
        # Hide for the most privileged buckets entirely.
        if dev_bypass_email and user.email == dev_bypass_email:
            return {"visible": False, "reason": "dev_bypass"}
        if user.email in studio_grant_emails:
            return {"visible": False, "reason": "studio_grant"}

        buyer = await db.buyers.find_one({"email": user.email}) or {}
        if buyer.get("founders"):
            return {"visible": False, "reason": "founder"}

        tier_id = (buyer.get("tier") or "").strip().lower()
        if tier_id == "t3":
            return {"visible": False, "reason": "top_tier"}

        sumo_url = (os.environ.get("APPSUMO_STACK_URL") or "").strip()
        own_url = (os.environ.get("OWN_PRICING_URL") or "").strip()

        if _campaign_active_now() and sumo_url:
            return {
                "visible": True,
                "url": sumo_url,
                "label": "Stack codes on AppSumo",
                "destination": "appsumo",
            }
        if own_url:
            return {
                "visible": True,
                "url": own_url,
                "label": "Upgrade your plan",
                "destination": "own",
            }
        return {"visible": False, "reason": "no_url_configured"}

    # =====================================================================
    # Admin-only
    # =====================================================================

    @api.post("/admin/licenses/bulk-create")
    async def admin_bulk_create(payload: BulkCreateRequest, _admin=Depends(require_admin_dep)):
        """Bulk-create redemption codes. Idempotent: duplicate codes (case-
        insensitive) are silently skipped — counted in the `skipped` field
        of the response. Accepts EITHER `codes: [{code, tier, notes?}]` OR
        a `csv:` blob with header row `code,tier[,notes]`."""
        rows = _parse_bulk_payload(payload)
        if not rows:
            raise HTTPException(status_code=400, detail="No rows found in the upload.")

        source = (payload.source or "appsumo").strip().lower()
        batch_id = (payload.batch_id or _default_batch_id()).strip() or None

        now_iso = _iso_now()
        created, skipped, invalid = 0, 0, []
        for raw_code, raw_tier, notes in rows:
            code = _normalize_code(raw_code)
            tier_id = (raw_tier or "").strip().lower()
            if not _is_plausible_code(code):
                invalid.append({"code": raw_code, "reason": "format"})
                continue
            if tier_id not in REDEEMABLE_TIER_IDS:
                invalid.append({"code": code, "reason": "tier"})
                continue
            try:
                await db.redemption_codes.insert_one({
                    "_id": code,
                    "tier": tier_id,
                    "source": source,
                    "status": "available",
                    "batch_id": batch_id,
                    "notes": notes or None,
                    "created_at": now_iso,
                    "redeemed_by": None,
                    "redeemed_at": None,
                })
                created += 1
            except Exception as exc:  # noqa: BLE001 — duplicate key etc
                if "duplicate" in str(exc).lower() or "E11000" in str(exc):
                    skipped += 1
                else:
                    logger.warning("[licenses] insert failed: %s", exc)
                    invalid.append({"code": code, "reason": "db_error"})

        return {
            "ok": True,
            "created": created,
            "skipped_duplicates": skipped,
            "invalid": invalid,
            "batch_id": batch_id,
        }

    @api.get("/admin/licenses")
    async def admin_list_licenses(
        status: Optional[str] = None,
        tier: Optional[str] = None,
        source: Optional[str] = None,
        batch_id: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
        _admin=Depends(require_admin_dep),
    ):
        """List redemption codes with optional filters. Limited to 200 per
        call so the admin UI stays snappy on large batches; the dashboard
        can paginate via `q` if needed."""
        filt: dict = {}
        if status: filt["status"] = status.strip().lower()
        if tier:   filt["tier"] = tier.strip().lower()
        if source: filt["source"] = source.strip().lower()
        if batch_id: filt["batch_id"] = batch_id.strip()
        if q:
            # Free-text search on code or redeemed_by — case-insensitive.
            qs = re.escape(q.strip())
            filt["$or"] = [
                {"_id": {"$regex": qs, "$options": "i"}},
                {"redeemed_by": {"$regex": qs, "$options": "i"}},
            ]

        cursor = db.redemption_codes.find(filt).sort([("created_at", -1)]).limit(max(1, min(500, limit)))

        items = []
        async for doc in cursor:
            items.append({
                "code": doc.get("_id"),
                "tier": doc.get("tier"),
                "source": doc.get("source"),
                "status": doc.get("status"),
                "batch_id": doc.get("batch_id"),
                "redeemed_by": doc.get("redeemed_by"),
                "redeemed_at": doc.get("redeemed_at"),
                "created_at": doc.get("created_at"),
                "notes": doc.get("notes"),
            })

        # Totals are useful for the admin dashboard header ("142 of 500
        # redeemed"). Cheap to compute via aggregation.
        totals = {"available": 0, "redeemed": 0, "void": 0}
        pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        async for row in db.redemption_codes.aggregate(pipeline):
            key = (row.get("_id") or "").strip().lower()
            if key in totals:
                totals[key] = row.get("n", 0)

        return {"items": items, "totals": totals}

    @api.post("/admin/licenses/{code}/void")
    async def admin_void_license(code: str, _admin=Depends(require_admin_dep)):
        """Void a code (e.g. someone refunded, code leaked, fraud). Voided
        codes can never be redeemed; existing redemptions are NOT reversed."""
        normalized = _normalize_code(code)
        result = await db.redemption_codes.update_one(
            {"_id": normalized},
            {"$set": {"status": "void", "voided_at": _iso_now()}},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Code not found")
        return {"ok": True}

    @api.post("/admin/buyers/{email}/upgrade-tier")
    async def admin_upgrade_buyer(
        email: str,
        payload: UpgradeTierRequest = Body(...),
        _admin=Depends(require_admin_dep),
    ):
        """Manual tier bump (or downshift) for a specific buyer. Used when
        someone bought outside the redemption flow (Stripe, direct invoice,
        partner promo) and admin needs to grant them their tier. Keeps the
        cycle clock when bumping mid-cycle — same rule as redemption."""
        tier_id = (payload.tier or "").strip().lower()
        if tier_id not in REDEEMABLE_TIER_IDS and tier_id != "founder":
            raise HTTPException(status_code=400, detail="Unknown tier")

        buyer = await db.buyers.find_one({"email": email})
        if not buyer:
            raise HTTPException(status_code=404, detail="Buyer not found")

        if tier_id == "founder":
            await db.buyers.update_one(
                {"email": email},
                {"$set": {
                    "founders": True,
                    "tier": "founder",
                    "updatedAt": _iso_now(),
                }},
            )
            return {"ok": True, "tier": "founder", "founders": True}

        current_tier = (buyer.get("tier") or "").strip().lower()
        is_first = current_tier not in REDEEMABLE_TIER_IDS
        fields = assign_buyer_to_tier(tier_id=tier_id, is_upgrade=not is_first)
        fields["updatedAt"] = _iso_now()
        fields.setdefault("source", buyer.get("source") or "manual")
        await db.buyers.update_one({"email": email}, {"$set": fields})

        await log_activity("admin_tier_bump", email, {
            "from": current_tier or "(none)", "to": tier_id,
        })
        return {"ok": True, "tier": tier_id, "tier_label": get_tier(tier_id).label}


# ============================================================================
# Module-level helpers
# ============================================================================

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tier_rank(tier_id: Optional[str]) -> int:
    """0-indexed rank in TIERS_ORDERED. Unknown tiers rank -1 so any real
    tier beats them and a first-time redemption goes through. Founder is
    intentionally NOT in TIERS_ORDERED — it's handled separately."""
    if not tier_id:
        return -1
    for i, t in enumerate(TIERS_ORDERED):
        if t.id == tier_id:
            return i
    return -1


def _default_batch_id() -> str:
    """Generate a deterministic batch id for admin bulk-imports that don't
    specify one. Format: `YYYYMMDD-HHMM` (UTC) — sortable, human-readable,
    no UUID noise in admin filter dropdowns."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")


def _parse_bulk_payload(payload: BulkCreateRequest) -> list[tuple[str, str, Optional[str]]]:
    """Normalize either `codes` array or `csv` blob into a flat list of
    (code, tier, notes) tuples. Returns empty list if neither shape is
    present — caller raises 400 in that case."""
    rows: list[tuple[str, str, Optional[str]]] = []

    if payload.codes:
        for entry in payload.codes:
            if not isinstance(entry, dict):
                continue
            rows.append((
                str(entry.get("code") or "").strip(),
                str(entry.get("tier") or "").strip(),
                (entry.get("notes") or None),
            ))

    if payload.csv:
        # Use csv.DictReader so we tolerate quoted cells + UTF-8 BOM. Header
        # row required. Column order is flexible (we lookup by name).
        text = (payload.csv or "").lstrip("\ufeff")
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                if not row:
                    continue
                # Accept "code", "Code", "CODE", " code "
                code_col = next((row[k] for k in row if k.strip().lower() == "code"), "") or ""
                tier_col = next((row[k] for k in row if k.strip().lower() == "tier"), "") or ""
                notes_col = next((row[k] for k in row if k.strip().lower() == "notes"), None)
                if not code_col.strip():
                    continue
                rows.append((code_col.strip(), tier_col.strip(), notes_col))
        except csv.Error as exc:
            logger.warning("[licenses] CSV parse failure: %s", exc)
            # Fall through — partial rows are still useful.

    return rows
