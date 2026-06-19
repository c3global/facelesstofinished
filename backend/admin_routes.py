"""Admin Panel + Pinball webhook + Netlify buyer import endpoints.

Scope per Charity's three prompts (one deployment):
  - Phase A: native /api/admin/* endpoints (Buyers, Activity, Stats) gated by JWT isAdmin
  - Phase B: /api/admin/buyers/import — admin-triggered batch upsert from Netlify
  - Phase C: /api/pinball-webhook — token-gated webhook receiver for Pinball.dev events

All endpoints live in the same FastAPI sub-app instance from server.py (`api`),
mounted at /api. We pull `db`, `api`, `current_user`, `ADMIN_EMAILS`, `KNOWN_ENTITLEMENTS`
and a `_log_activity` helper from server.py at wiring time to keep this module
declarative and import-cycle-free.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("f48.admin")

# Shared secret for Pinball.dev → emergent webhook. Single gate, no HMAC.
# Same value Netlify uses, so both sides can run in parallel during cutover.
PINBALL_WEBHOOK_TOKEN = os.environ.get("PINBALL_WEBHOOK_TOKEN", "").strip()

# Studio "lifetime" entitlement metadata when granted via Pinball.
STUDIO_LIFETIME_PERIOD_END = "2099-01-01T00:00:00Z"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class BuyerEntitlementChange(BaseModel):
    entitlement: str


class BulkDeleteRequest(BaseModel):
    emails: list[str] = Field(default_factory=list)


class BuyerImportRow(BaseModel):
    email: str
    entitlements: list[str] = Field(default_factory=list)
    totalSpendCents: float = 0
    seenOrderIds: list[str] = Field(default_factory=list)
    orderId: Optional[str] = None
    addedAt: Optional[str] = None
    lastLoginAt: Optional[str] = None
    loginCount: int = 0
    scriptCount: int = 0
    shortsCount: int = 0
    firstUseAt: Optional[str] = None
    source: Optional[str] = None
    event: Optional[str] = None


class BuyerImportRequest(BaseModel):
    buyers: list[BuyerImportRow] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept trailing Z or full ISO with offset
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _iso_min(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Earlier-wins for addedAt / firstUseAt. Never overwrite existing with null."""
    da, db = _parse_iso(a), _parse_iso(b)
    if da and db:
        return a if da <= db else b
    return a or b


def _iso_max(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Later-wins for lastLoginAt. Never overwrite existing with null."""
    da, db = _parse_iso(a), _parse_iso(b)
    if da and db:
        return a if da >= db else b
    return a or b


def _strip_id(doc: dict) -> dict:
    """Drop Mongo's `_id` ObjectId so the response is JSON-serialisable."""
    if doc and "_id" in doc:
        doc = {k: v for k, v in doc.items() if k != "_id"}
    return doc


# ---------------------------------------------------------------------------
# Wiring entrypoint
# ---------------------------------------------------------------------------
def register_admin_routes(
    *,
    api,
    db,
    current_user,
    ADMIN_EMAILS,
    KNOWN_ENTITLEMENTS,
    log_activity,
):
    """Attach all admin routes + pinball webhook to the shared `api` FastAPI sub-app."""

    async def require_admin(user=Depends(current_user)):
        if not (user.is_admin or user.email.lower() in ADMIN_EMAILS):
            raise HTTPException(status_code=403, detail="Admin only")
        return user

    # ---- Buyers list ----
    @api.get("/admin/buyers")
    async def admin_list_buyers(
        q: Optional[str] = Query(None, description="Case-insensitive email substring"),
        entitlement: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        skip: int = Query(0, ge=0),
        _admin=Depends(require_admin),
    ):
        query: dict[str, Any] = {}
        if q:
            query["email"] = {"$regex": re.escape(q.strip().lower()), "$options": "i"}
        if entitlement:
            query["entitlements"] = entitlement
        total = await db.buyers.count_documents(query)
        cursor = (
            db.buyers.find(query)
            .sort([("addedAt", -1)])
            .skip(skip)
            .limit(limit)
        )
        items = [_strip_id(b) async for b in cursor]
        return {"total": total, "items": items}

    # ---- Grant entitlement ----
    @api.patch("/admin/buyers/{email}/grant")
    async def admin_grant(
        email: str,
        payload: BuyerEntitlementChange = Body(...),
        admin=Depends(require_admin),
    ):
        ent = payload.entitlement.strip().lower()
        if ent not in KNOWN_ENTITLEMENTS:
            raise HTTPException(status_code=400, detail=f"Unknown entitlement: {ent}")
        email_l = email.strip().lower()
        if not EMAIL_RE.match(email_l):
            raise HTTPException(status_code=400, detail="Invalid email")
        await db.buyers.update_one(
            {"email": email_l},
            {
                "$addToSet": {"entitlements": ent},
                "$set": {"updatedAt": _now_iso()},
                "$setOnInsert": {"email": email_l, "addedAt": _now_iso(), "source": "admin"},
            },
            upsert=True,
        )
        await log_activity(
            "admin_grant",
            admin.email,
            {"buyer": email_l, "entitlement": ent},
        )
        doc = _strip_id(await db.buyers.find_one({"email": email_l}) or {})
        return {"ok": True, "buyer": doc}

    @api.patch("/admin/buyers/{email}/revoke")
    async def admin_revoke(
        email: str,
        payload: BuyerEntitlementChange = Body(...),
        admin=Depends(require_admin),
    ):
        ent = payload.entitlement.strip().lower()
        email_l = email.strip().lower()
        r = await db.buyers.update_one(
            {"email": email_l},
            {"$pull": {"entitlements": ent}, "$set": {"updatedAt": _now_iso()}},
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Buyer not found")
        await log_activity(
            "admin_revoke",
            admin.email,
            {"buyer": email_l, "entitlement": ent},
        )
        doc = _strip_id(await db.buyers.find_one({"email": email_l}) or {})
        return {"ok": True, "buyer": doc}

    @api.delete("/admin/buyers/{email}")
    async def admin_delete_buyer(email: str, admin=Depends(require_admin)):
        email_l = email.strip().lower()
        r = await db.buyers.delete_one({"email": email_l})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Buyer not found")
        await log_activity("admin_delete_buyer", admin.email, {"buyer": email_l})
        return {"ok": True}

    @api.post("/admin/buyers/bulk-delete")
    async def admin_bulk_delete(payload: BulkDeleteRequest, admin=Depends(require_admin)):
        emails = [e.strip().lower() for e in payload.emails if e and e.strip()]
        if not emails:
            return {"deleted": 0}
        r = await db.buyers.delete_many({"email": {"$in": emails}})
        await log_activity(
            "admin_bulk_delete",
            admin.email,
            {"count": r.deleted_count, "emails": emails},
        )
        return {"deleted": r.deleted_count}

    # ---- Buyer import (Phase B) ----
    @api.post("/admin/buyers/import")
    async def admin_import_buyers(payload: BuyerImportRequest, admin=Depends(require_admin)):
        imported = 0
        merged = 0
        skipped = 0
        errors: list[dict] = []

        for row in payload.buyers:
            email_l = (row.email or "").strip().lower()
            if not EMAIL_RE.match(email_l):
                errors.append({"email": row.email, "reason": "invalid email"})
                skipped += 1
                continue
            try:
                existing = await db.buyers.find_one({"email": email_l})
                if existing is None:
                    doc = {
                        "email": email_l,
                        "entitlements": sorted(set(row.entitlements or [])),
                        "totalSpendCents": int(row.totalSpendCents or 0),
                        "seenOrderIds": sorted(set(row.seenOrderIds or [])),
                        "orderId": row.orderId,
                        "addedAt": row.addedAt or _now_iso(),
                        "lastLoginAt": row.lastLoginAt,
                        "loginCount": int(row.loginCount or 0),
                        "scriptCount": int(row.scriptCount or 0),
                        "shortsCount": int(row.shortsCount or 0),
                        "firstUseAt": row.firstUseAt,
                        "source": row.source or "netlify-import",
                        "event": row.event,
                        "updatedAt": _now_iso(),
                    }
                    await db.buyers.insert_one(doc)
                    imported += 1
                else:
                    merged_ents = sorted(set(existing.get("entitlements") or []) | set(row.entitlements or []))
                    merged_orders = sorted(set(existing.get("seenOrderIds") or []) | set(row.seenOrderIds or []))
                    # max() counters
                    set_doc = {
                        "entitlements": merged_ents,
                        "seenOrderIds": merged_orders,
                        "totalSpendCents": max(int(existing.get("totalSpendCents") or 0), int(row.totalSpendCents or 0)),
                        "loginCount": max(int(existing.get("loginCount") or 0), int(row.loginCount or 0)),
                        "scriptCount": max(int(existing.get("scriptCount") or 0), int(row.scriptCount or 0)),
                        "shortsCount": max(int(existing.get("shortsCount") or 0), int(row.shortsCount or 0)),
                        # earliest-wins timestamps; never overwrite with null
                        "addedAt": _iso_min(existing.get("addedAt"), row.addedAt) or _now_iso(),
                        "firstUseAt": _iso_min(existing.get("firstUseAt"), row.firstUseAt),
                        # latest-wins timestamps; never overwrite with null
                        "lastLoginAt": _iso_max(existing.get("lastLoginAt"), row.lastLoginAt),
                        "updatedAt": _now_iso(),
                    }
                    # never null-overwrite for these scalar fields either
                    if row.orderId:
                        set_doc["orderId"] = row.orderId
                    if row.source:
                        set_doc["source"] = row.source
                    if row.event:
                        set_doc["event"] = row.event
                    await db.buyers.update_one({"email": email_l}, {"$set": set_doc})
                    merged += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[import] {email_l}: {type(exc).__name__}: {exc}")
                errors.append({"email": email_l, "reason": f"{type(exc).__name__}: {exc}"})
                skipped += 1

        await log_activity(
            "admin_buyers_import",
            admin.email,
            {"imported": imported, "merged": merged, "skipped": skipped, "error_count": len(errors)},
        )
        return {"imported": imported, "merged": merged, "skipped": skipped, "errors": errors}

    # ---- Activity log ----
    @api.get("/admin/activity")
    async def admin_list_activity(
        type: Optional[str] = Query(None),
        email: Optional[str] = Query(None),
        date_from: Optional[str] = Query(None, description="ISO date (inclusive)"),
        date_to: Optional[str] = Query(None, description="ISO date (inclusive)"),
        limit: int = Query(200, ge=1, le=1000),
        skip: int = Query(0, ge=0),
        _admin=Depends(require_admin),
    ):
        query: dict[str, Any] = {}
        if type:
            query["type"] = type
        if email:
            query["email"] = {"$regex": re.escape(email.strip().lower()), "$options": "i"}
        if date_from or date_to:
            ts_q: dict[str, Any] = {}
            if date_from:
                ts_q["$gte"] = date_from
            if date_to:
                ts_q["$lte"] = date_to
            query["ts"] = ts_q
        total = await db.activity.count_documents(query)
        cursor = db.activity.find(query).sort([("ts", -1)]).skip(skip).limit(limit)
        items = [_strip_id(d) async for d in cursor]
        return {"total": total, "items": items}

    @api.post("/admin/activity/{activity_id}/replay")
    async def admin_replay_activity(activity_id: str, admin=Depends(require_admin)):
        """Replay a failed Pinball webhook locally (no external network call).
        We pull the original payload + product from the saved detail and run
        it back through the same handler logic in-process — same dedupe, same
        merge, same activity log. Safe to invoke repeatedly; the seenOrderIds
        dedupe will return `{status: "duplicate"}` on the second run."""
        doc = await db.activity.find_one({"id": activity_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Activity not found")
        if doc.get("type") != "webhook_failed":
            raise HTTPException(status_code=400, detail="Only webhook_failed events can be replayed")
        detail = doc.get("detail") or {}
        product = detail.get("product")
        body = detail.get("payload") or {}
        if not product or not body:
            raise HTTPException(status_code=400, detail="Activity is missing product/payload")
        result = await _process_pinball_event(product=product, body=body, source="replay")
        await log_activity(
            "admin_replay",
            admin.email,
            {"original_id": activity_id, "result": result},
        )
        return {"ok": True, "result": result}

    @api.delete("/admin/activity/{activity_id}")
    async def admin_delete_activity(activity_id: str, admin=Depends(require_admin)):
        r = await db.activity.delete_one({"id": activity_id})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Activity not found")
        await log_activity("admin_delete_activity", admin.email, {"id": activity_id})
        return {"ok": True}

    @api.post("/admin/activity/bulk-delete")
    async def admin_bulk_delete_activity(
        payload: dict = Body(...),
        admin=Depends(require_admin),
    ):
        ids = [str(i) for i in (payload.get("ids") or []) if i]
        wipe_all = bool(payload.get("wipe_all"))
        if wipe_all:
            r = await db.activity.delete_many({})
            await log_activity("admin_wipe_activity", admin.email, {"deleted": r.deleted_count})
            return {"deleted": r.deleted_count, "wiped_all": True}
        if not ids:
            return {"deleted": 0}
        r = await db.activity.delete_many({"id": {"$in": ids}})
        await log_activity(
            "admin_bulk_delete_activity",
            admin.email,
            {"count": r.deleted_count, "ids": ids},
        )
        return {"deleted": r.deleted_count}

    # ---- Stats ----
    @api.get("/admin/stats")
    async def admin_stats(_admin=Depends(require_admin)):
        # Total counts
        total_users = await db.buyers.count_documents({})
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        active_30d = await db.buyers.count_documents({"lastLoginAt": {"$gte": thirty_days_ago}})

        # Signups over time — group by date (YYYY-MM-DD) on addedAt
        # Fall back to bucketing in Python if we have heterogeneous timestamp formats.
        signups: dict[str, int] = {}
        async for doc in db.buyers.find({}, {"addedAt": 1}):
            ts = doc.get("addedAt")
            if not ts:
                continue
            day = ts[:10]  # ISO `YYYY-MM-DD`
            signups[day] = signups.get(day, 0) + 1
        signups_series = [{"date": d, "count": signups[d]} for d in sorted(signups.keys())]

        # Engagement
        total_renders = await db.renders.count_documents({})
        total_scripts = await db.scripts.count_documents({})

        # Revenue sum (cents)
        revenue_cents = 0
        async for doc in db.buyers.find({}, {"totalSpendCents": 1}):
            revenue_cents += int(doc.get("totalSpendCents") or 0)

        # Entitlement breakdown
        ent_breakdown: dict[str, int] = {}
        for ent in KNOWN_ENTITLEMENTS:
            ent_breakdown[ent] = await db.buyers.count_documents({"entitlements": ent})

        return {
            "total_users": total_users,
            "active_30d": active_30d,
            "total_renders": total_renders,
            "total_scripts": total_scripts,
            "revenue_cents": revenue_cents,
            "entitlement_breakdown": ent_breakdown,
            "signups_series": signups_series,
        }

    # ---- Pinball webhook (Phase C) ----
    async def _process_pinball_event(*, product: str, body: dict, source: str) -> dict:
        """Pure handler shared by the public webhook endpoint and the admin
        Replay action. Idempotent — duplicate order_ids no-op."""
        product = (product or "").strip().lower()
        if product not in KNOWN_ENTITLEMENTS:
            await log_activity(
                "webhook_failed",
                body.get("email", ""),
                {"reason": "unknown product", "product": product, "payload": body, "source": source},
            )
            raise HTTPException(status_code=400, detail=f"Unknown product: {product}")

        email = (body.get("email") or "").strip().lower()
        if not email or not EMAIL_RE.match(email):
            await log_activity(
                "webhook_failed",
                email,
                {"reason": "missing or malformed email", "product": product, "payload": body, "source": source},
            )
            raise HTTPException(status_code=400, detail="Missing or malformed email")

        order_id = (body.get("order_id") or "").strip()
        try:
            total_amount = int(body.get("total_amount") or 0)
        except (ValueError, TypeError):
            total_amount = 0

        existing = await db.buyers.find_one({"email": email})

        # Dedupe by order_id
        if order_id and existing and order_id in (existing.get("seenOrderIds") or []):
            await log_activity(
                "webhook",
                email,
                {"status": "duplicate", "product": product, "order_id": order_id, "payload": body, "source": source},
            )
            return {"status": "duplicate", "order_id": order_id}

        # Build the entitlement merge.
        new_ents = sorted(set((existing.get("entitlements") if existing else []) or []) | {product})

        set_doc: dict[str, Any] = {
            "email": email,
            "entitlements": new_ents,
            "totalSpendCents": int((existing.get("totalSpendCents") if existing else 0) or 0) + total_amount,
            "updatedAt": _now_iso(),
            "source": "webhook" if not existing else (existing.get("source") or "webhook"),
        }
        push_doc: dict[str, Any] = {}
        if order_id:
            push_doc["seenOrderIds"] = order_id
            set_doc["orderId"] = order_id

        # Studio-specific lifetime metadata.
        if product == "studio":
            set_doc["studio_status"] = "active"
            set_doc["studio_lifetime"] = True
            set_doc["studio_current_period_end"] = STUDIO_LIFETIME_PERIOD_END

        update: dict[str, Any] = {"$set": set_doc}
        if push_doc:
            update["$addToSet"] = push_doc
        if not existing:
            update["$setOnInsert"] = {"addedAt": _now_iso()}

        await db.buyers.update_one({"email": email}, update, upsert=True)

        await log_activity(
            "webhook",
            email,
            {"status": "ok", "product": product, "order_id": order_id, "payload": body, "source": source},
        )
        return {"status": "ok", "product": product, "order_id": order_id, "email": email}

    @api.post("/pinball-webhook")
    async def pinball_webhook(
        request: Request,
        token: str = Query(...),
        product: str = Query(...),
    ):
        # 1) Token gate. Compare in constant-ish time. Empty configured value
        #    means "endpoint disabled" — we still log the rejection so admin
        #    can tell whether GHL is firing at us.
        if not PINBALL_WEBHOOK_TOKEN or token != PINBALL_WEBHOOK_TOKEN:
            try:
                body = await request.json()
            except Exception:
                body = {"_raw": (await request.body()).decode("utf-8", "replace")[:1000]}
            await log_activity(
                "webhook_failed",
                (body.get("email") or "") if isinstance(body, dict) else "",
                {"reason": "invalid token", "product": product, "payload": body, "source": "pinball"},
            )
            raise HTTPException(status_code=401, detail="Invalid token")

        # 2) Parse + dispatch
        try:
            body = await request.json()
        except Exception:
            await log_activity(
                "webhook_failed",
                "",
                {"reason": "malformed json", "product": product, "source": "pinball"},
            )
            raise HTTPException(status_code=400, detail="Malformed JSON")

        return await _process_pinball_event(product=product, body=body, source="pinball")

    return {"process_pinball_event": _process_pinball_event}
