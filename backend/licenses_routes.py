"""License code redemption + bulk provisioning + tier upgrades.

This module powers the AppSumo launch (and any future code-based acquisition
channel — partner codes, agency reseller codes, beta codes). Crucially, the
CUSTOMER-FACING surface never says "AppSumo": the /redeem page accepts any
code regardless of source, and admin reporting separates codes by their
`source` field for the operator's eyes only.

Schema:
    db.redemption_codes:
        _id:         the code string (uppercased, dashes preserved)
        tier:        "t1" | "t2" | "t3" | "t4"  (Founder is intentionally
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
        rule we locked with the user on 2026-06-29)."""
        code = _normalize_code(payload.code)
        if not _is_plausible_code(code):
            raise HTTPException(
                status_code=400,
                detail="That doesn't look like a valid code. Double-check the email it came in.",
            )

        record = await db.redemption_codes.find_one({"_id": code})
        if not record:
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
            if (record.get("redeemed_by") or "").lower() == user.email.lower():
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

        # Look up the buyer doc. If it doesn't exist (rare — every signed-in
        # user usually has one), provision a fresh one with the redeemed tier.
        buyer = await db.buyers.find_one({"email": user.email})
        now_iso = _iso_now()

        # Founders + dev bypass + studio grant emails are NEVER demoted by a
        # redemption. We still mark the code redeemed (so it can't be reused
        # elsewhere) but the buyer doc stays as-is.
        is_protected = (
            (dev_bypass_email and user.email == dev_bypass_email)
            or user.email in studio_grant_emails
            or bool((buyer or {}).get("founders"))
        )

        if not is_protected:
            current_tier_id = ((buyer or {}).get("tier") or "").strip().lower()
            is_first_time = not current_tier_id or current_tier_id not in REDEEMABLE_TIER_IDS
            # Only bump if the new tier is strictly HIGHER. Downgrades via
            # redemption would be a footgun — if a T3 buyer accidentally
            # redeems a T1 code, we keep them at T3 and burn the code anyway
            # (to prevent reuse) but flag it for admin review.
            current_rank = _tier_rank(current_tier_id)
            new_rank = _tier_rank(tier_id)

            if new_rank > current_rank:
                tier_fields = assign_buyer_to_tier(
                    tier_id=tier_id,
                    is_upgrade=not is_first_time,
                )
                tier_fields.setdefault("source", record.get("source") or "appsumo")
                tier_fields.setdefault("orderId", code)
                tier_fields["lastRedeemedCode"] = code
                tier_fields["updatedAt"] = now_iso
                if is_first_time:
                    tier_fields.setdefault("addedAt", now_iso)
                    tier_fields.setdefault("firstUseAt", now_iso)
                await db.buyers.update_one(
                    {"email": user.email},
                    {
                        "$set": tier_fields,
                        "$setOnInsert": {"email": user.email, "founders": False},
                    },
                    upsert=True,
                )
            else:
                # Code burned, but buyer stays at current (higher) tier.
                logger.info(
                    "[licenses] redeem skipped tier bump: user=%s current=%s code_tier=%s code=%s",
                    user.email, current_tier_id, tier_id, code,
                )

        # Atomic flip on the code record so two concurrent redeems can't both
        # win the race. The status filter `available` is the race lock.
        flipped = await db.redemption_codes.find_one_and_update(
            {"_id": code, "status": "available"},
            {"$set": {
                "status": "redeemed",
                "redeemed_by": user.email,
                "redeemed_at": now_iso,
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

        await log_activity("license_redeemed", user.email, {
            "code": code,
            "tier": tier_id,
            "source": record.get("source"),
            "batch_id": record.get("batch_id"),
        })

        return {
            "ok": True,
            "tier": tier_id,
            "tier_label": get_tier(tier_id).label,
            "message": f"Welcome — you're on {get_tier(tier_id).label}.",
        }

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
        if tier_id == "t4":
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
