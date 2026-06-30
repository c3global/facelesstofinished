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

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("f48.admin")

# Shared secret for Pinball.dev → emergent webhook. Single gate, no HMAC.
# Same value Netlify uses, so both sides can run in parallel during cutover.
PINBALL_WEBHOOK_TOKEN = os.environ.get("PINBALL_WEBHOOK_TOKEN", "").strip()

# Pinball product_id → entitlement mapping. JSON map in env var so the
# user can edit without code changes when she launches new products.
# Default falls back to Charity's current 4 products.
DEFAULT_PINBALL_PRODUCT_MAP = {
    "01ks3pmetahzgx2mfg7q5crs0j": "base",    # Faceless to Finished in 48 (main)
    "01ks3tjfdy0pmpbkzrj6vtg9r7": "base",    # Niche & Topic Vault (bump → bundled with base)
    "01ksgx97wad7vcc27ycvw0erg7": "shorts",  # Faceless Shorts (upsell 1)
    "01kv67kgk9z028tn0hy1kzk92r": "studio",  # Studio Founder Lifetime (upsell 2)
}
try:
    _env_map = os.environ.get("PINBALL_PRODUCT_MAP", "").strip()
    PINBALL_PRODUCT_MAP = json.loads(_env_map) if _env_map else DEFAULT_PINBALL_PRODUCT_MAP
except json.JSONDecodeError:
    logger.warning("PINBALL_PRODUCT_MAP env var is not valid JSON, falling back to defaults")
    PINBALL_PRODUCT_MAP = DEFAULT_PINBALL_PRODUCT_MAP

# Studio "lifetime" entitlement metadata when granted via Pinball.
STUDIO_LIFETIME_PERIOD_END = "2099-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Lenient payload extractors — Pinball / GHL webhooks ship the same
# *semantic* data under different *shapes* depending on which workflow node
# fires (raw checkout, OTO, replay, etc). The legacy Netlify handler
# (/app/legacy_netlify/netlify/functions/pinball-webhook.mjs) accepted six
# email paths + four items paths + six order-id paths. We mirror that
# tolerance here so workflows that worked on Netlify keep working on Emergent
# without any Pinball-side reconfiguration.
# ---------------------------------------------------------------------------
def _extract_email(p: dict) -> str:
    paths = [
        ("customer", "email"),
        ("data", "customer", "email"),
        ("data", "email"),
        ("order", "customer", "email"),
        ("data", "order", "customer", "email"),
        ("email",),
        ("contact", "email"),
        ("data", "contact", "email"),
    ]
    for path in paths:
        node = p
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, str) and node.strip():
            return node.strip().lower()
    return ""


def _extract_items(p: dict) -> list:
    """Locate the line-items array in a webhook payload. Pinball / GHL /
    Kajabi / Stripe all use different naming conventions; we accept all of
    them so existing funnels keep working without per-provider config.

    Supported paths (snake_case AND camelCase):
      items, lineItems, line_items, products
      data.<same>, order.<same>, data.order.<same>, event.<same>
    Plus: data.order.products on some Kajabi flows.
    """
    keys = ("items", "lineItems", "line_items", "products")
    prefixes: list[tuple] = [
        (),                       # top-level
        ("data",),
        ("order",),
        ("data", "order"),
        ("event",),
        ("data", "event"),
        ("payload",),
        ("data", "payload"),
    ]
    for prefix in prefixes:
        for key in keys:
            path = (*prefix, key)
            node = p
            for k in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            if isinstance(node, list) and node:
                return node
    return []


def _synthesize_single_item(p: dict) -> Optional[dict]:
    """When the payload has NO items array but DOES have product info at
    the top level (or under data/order), build a synthetic single-item dict
    so the rest of the pipeline can treat it like a one-line order. This
    is how most GHL "Order Submitted" workflow nodes ship — they flatten
    the order into individual fields rather than nesting an items array."""
    candidates = [p, p.get("data") if isinstance(p.get("data"), dict) else {},
                  p.get("order") if isinstance(p.get("order"), dict) else {}]
    for node in candidates:
        if not isinstance(node, dict):
            continue
        product_id = (
            node.get("product_id") or node.get("productId")
            or node.get("product") or node.get("sku")
        )
        if not product_id:
            continue
        return {
            "id": (node.get("line_item_id") or node.get("id") or node.get("order_id")
                   or node.get("orderId") or ""),
            "product_id": str(product_id),
            "product_name": (node.get("product_name") or node.get("productName")
                             or node.get("name") or ""),
            "amount": node.get("amount") or node.get("price") or 0,
        }
    return None


def _extract_order_id(p: dict) -> str:
    for path in [
        ("order", "id"),
        ("data", "order", "id"),
        ("order_id",),
        ("data", "order_id"),
        ("id",),
        ("data", "id"),
    ]:
        node = p
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if node:
            return str(node).strip()
    return ""


def _extract_order_total_cents(p: dict) -> int:
    """Locate the order total in cents. Like _extract_email/_extract_items,
    accepts the multiple shapes Pinball/GHL/Kajabi ship. Returns 0 if
    nothing parseable is found (better to grant without tracking spend than
    to drop the entire webhook over a missing amount field).

    Field-name heuristic:
      - `total_amount` / `total_amount_cents` → Pinball convention = CENTS
      - `amount` / `total` / `price` → Stripe/GHL/Kajabi convention = DOLLARS
      - Floats are always DOLLARS (e.g. 27.0 → 2700)
      - Large ints (>= 10000) on `amount`/`total`/`price` are still treated
        as cents (defensive — Stripe sometimes ships cents under `amount`).
    """
    cents_paths = [
        ("total_amount",),
        ("data", "total_amount"),
        ("order", "total_amount"),
        ("data", "order", "total_amount"),
        ("total_amount_cents",),
        ("data", "total_amount_cents"),
    ]
    dollar_paths = [
        ("amount",),
        ("data", "amount"),
        ("order", "amount"),
        ("data", "order", "amount"),
        ("total",),
        ("data", "total"),
        ("order", "total"),
        ("data", "order", "total"),
        ("price",),
        ("data", "price"),
    ]

    def _read(path: tuple) -> object:
        node = p
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    # 1) Cents-named fields take precedence + are NEVER multiplied.
    for path in cents_paths:
        v = _read(path)
        if v is None:
            continue
        try:
            return int(round(float(v)))
        except (ValueError, TypeError):
            continue

    # 2) Dollar-named fields: float → cents via ×100; large int → cents.
    for path in dollar_paths:
        v = _read(path)
        if v is None:
            continue
        try:
            f = float(v)
        except (ValueError, TypeError):
            continue
        if isinstance(v, float) or (isinstance(v, str) and "." in v):
            return int(round(f * 100))
        # Integer-shaped: large = cents (Stripe), small = dollars (GHL).
        return int(round(f)) if f >= 10000 else int(round(f * 100))
    return 0


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

    @api.post("/admin/pinball/test-webhook")
    async def admin_pinball_test_webhook(
        payload: dict = Body(default_factory=dict),
        admin=Depends(require_admin),
    ):
        """Synthetic Pinball webhook ping — used by the Admin → Buyers UI's
        "Test webhook" button to verify the live webhook is wired correctly
        without bothering a real customer or running a paid test order.

        Builds a realistic payload (defaults to the base 'Faceless to Finished'
        product) and processes it through the SAME _process_pinball_event
        helper the live webhook uses. Marks the resulting buyer with
        `_synthetic: True` so admin reports can filter them out, and uses
        an email of the form `webhook-test+<timestamp>@faceless48.test`
        which never collides with a real customer.

        Optional body overrides:
          - `product_id`: defaults to the base product id (mapped to 'base')
          - `email`: defaults to a synthetic timestamped email
        """
        import time  # noqa: PLC0415

        product_id = (payload.get("product_id") or "01ks3pmetahzgx2mfg7q5crs0j").strip()
        entitlement = PINBALL_PRODUCT_MAP.get(product_id)
        if not entitlement:
            raise HTTPException(
                status_code=400,
                detail=f"product_id {product_id!r} is not in PINBALL_PRODUCT_MAP",
            )

        ts = int(time.time())
        email = (payload.get("email") or f"webhook-test+{ts}@faceless48.test").strip().lower()
        line_item_id = f"test-line-{ts}"

        try:
            result = await _process_pinball_event(
                product=entitlement,
                body={
                    "email": email,
                    "total_amount": "700",
                    "order_id": line_item_id,
                },
                source="admin-test",
            )
            # Tag the synthetic buyer so reports can filter it out.
            await db.buyers.update_one(
                {"email": email},
                {"$set": {"_synthetic": True, "_test_run_by": admin.email}},
            )
            return {
                "ok": True,
                "result": result,
                "test_email": email,
                "test_product": entitlement,
                "test_product_id": product_id,
                "message": (
                    f"Webhook is healthy. Synthetic buyer {email} created with "
                    f"entitlement '{entitlement}'. Click 'Delete' on that row "
                    "to clean up the test data."
                ),
            }
        except HTTPException as exc:
            return {
                "ok": False,
                "status_code": exc.status_code,
                "detail": exc.detail,
                "test_email": email,
                "test_product_id": product_id,
            }

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

    # ---- Per-customer Usage (Group A3 of the AppSumo launch plan) ----
    # Joins buyers + scripts + renders + activity into a single per-customer
    # leaderboard row so the upcoming Usage admin tab can show:
    #   email · tier · scripts (Long/Short/Sprint) · renders (Faceless/Avatar
    #   · complete/failed) · $ infra spent · last_seen · founder flag
    #
    # Uses MongoDB $facet to compute all aggregations in ONE round trip
    # rather than N+1 queries per buyer. Limits to 500 rows by default since
    # AppSumo deal sizes typically stay in the low-thousands range; cursor-
    # less pagination is fine for now.
    @api.get("/admin/usage")
    async def admin_usage(
        q: Optional[str] = Query(None, description="Case-insensitive email substring"),
        sort_by: str = Query(
            "last_seen",
            regex="^(last_seen|email|scripts_total|renders_total|spend_cents|added_at)$",
            description="Column to sort by",
        ),
        sort_dir: str = Query("desc", regex="^(asc|desc)$"),
        limit: int = Query(500, ge=1, le=2000),
        skip: int = Query(0, ge=0),
        _admin=Depends(require_admin),
    ):
        from tier_config import tier_for_entitlements  # local import — avoids top-level cycle risk

        # Build the buyer filter once — used both as the buyers cursor AND as
        # the email-set that scoping the script/render aggregations.
        bq: dict[str, Any] = {}
        if q:
            bq["email"] = {"$regex": re.escape(q.strip().lower()), "$options": "i"}

        # Pull buyer base rows first. We page on the buyer list, then enrich
        # in bulk — this keeps the response bounded even if a user has tens
        # of thousands of scripts. Total is the count for pagination UI.
        total = await db.buyers.count_documents(bq)
        buyers_cursor = db.buyers.find(
            bq,
            {
                "email": 1,
                "entitlements": 1,
                "tier": 1,
                "founders": 1,
                "lastLoginAt": 1,
                "loginCount": 1,
                "addedAt": 1,
                "totalSpendCents": 1,
            },
        ).sort([("email", 1)])
        buyer_docs = [b async for b in buyers_cursor]
        emails = [b["email"] for b in buyer_docs if b.get("email")]

        if not emails:
            return {"total": total, "items": []}

        # One aggregate per source collection, all keyed by user_email so we
        # can stitch back to buyers in O(1). Mongo handles the heavy lifting.
        async def _agg(coll, group: dict) -> dict[str, dict]:
            out: dict[str, dict] = {}
            pipeline = [
                {"$match": {"user_email": {"$in": emails}}},
                {"$group": group},
            ]
            async for row in coll.aggregate(pipeline):
                key = row.pop("_id", None)
                if isinstance(key, str):
                    out[key] = row
            return out

        scripts_by_email = await _agg(
            db.scripts,
            {
                "_id": "$user_email",
                "total": {"$sum": 1},
                "long":   {"$sum": {"$cond": [{"$eq": ["$mode", "long"]},   1, 0]}},
                "shorts": {"$sum": {"$cond": [{"$eq": ["$mode", "shorts"]}, 1, 0]}},
                "sprint": {"$sum": {"$cond": [{"$eq": ["$mode", "sprint"]}, 1, 0]}},
                "last_script_at": {"$max": "$created_at"},
            },
        )
        renders_by_email = await _agg(
            db.renders,
            {
                "_id": "$user_email",
                "total":    {"$sum": 1},
                "faceless": {"$sum": {"$cond": [{"$eq": ["$mode", "faceless"]}, 1, 0]}},
                "avatar":   {"$sum": {"$cond": [{"$eq": ["$mode", "avatar"]},   1, 0]}},
                "complete": {"$sum": {"$cond": [{"$eq": ["$status", "complete"]}, 1, 0]}},
                "failed":   {"$sum": {"$cond": [{"$eq": ["$status", "failed"]},   1, 0]}},
                "spend_cents": {"$sum": {"$ifNull": ["$actual_cost_cents", 0]}},
                "last_render_at": {"$max": "$created_at"},
            },
        )

        # Stitch buyers + aggregations. Tier resolution: prefer the explicit
        # `tier` field if migrated; otherwise derive from entitlements via
        # the tier_config helper (so pre-migration buyers still get labeled).
        items = []
        for b in buyer_docs:
            email = b.get("email") or ""
            ents = list(b.get("entitlements") or [])
            tier_id = (b.get("tier") or "").strip().lower()
            if not tier_id:
                tier_id = tier_for_entitlements(ents).id
            scripts_row = scripts_by_email.get(email, {})
            renders_row = renders_by_email.get(email, {})
            # last_seen = the latest of (lastLoginAt, last_script_at, last_render_at).
            # Buyers with no activity at all fall back to addedAt so the row
            # still sorts sanely.
            last_seen = _iso_max(b.get("lastLoginAt"), scripts_row.get("last_script_at"))
            last_seen = _iso_max(last_seen, renders_row.get("last_render_at"))
            if not last_seen:
                last_seen = b.get("addedAt")
            items.append({
                "email": email,
                "tier": tier_id,
                "entitlements": ents,
                "founder": bool(b.get("founders")),
                "last_seen": last_seen,
                "added_at": b.get("addedAt"),
                "login_count": int(b.get("loginCount") or 0),
                "scripts": {
                    "total":  int(scripts_row.get("total")  or 0),
                    "long":   int(scripts_row.get("long")   or 0),
                    "shorts": int(scripts_row.get("shorts") or 0),
                    "sprint": int(scripts_row.get("sprint") or 0),
                    "last_at": scripts_row.get("last_script_at"),
                },
                "renders": {
                    "total":    int(renders_row.get("total")    or 0),
                    "faceless": int(renders_row.get("faceless") or 0),
                    "avatar":   int(renders_row.get("avatar")   or 0),
                    "complete": int(renders_row.get("complete") or 0),
                    "failed":   int(renders_row.get("failed")   or 0),
                    "last_at":  renders_row.get("last_render_at"),
                },
                "spend_cents": int(renders_row.get("spend_cents") or 0),
                "buyer_total_spend_cents": int(b.get("totalSpendCents") or 0),
            })

        # Server-side sort + pagination AFTER stitching so we can sort on
        # derived columns (scripts_total, renders_total, spend_cents,
        # last_seen) that don't exist on any single source collection.
        sort_key_map = {
            "email":          lambda r: (r.get("email") or "").lower(),
            "scripts_total":  lambda r: r["scripts"]["total"],
            "renders_total":  lambda r: r["renders"]["total"],
            "spend_cents":    lambda r: r["spend_cents"],
            "last_seen":      lambda r: r.get("last_seen") or "",
            "added_at":       lambda r: r.get("added_at") or "",
        }
        items.sort(key=sort_key_map[sort_by], reverse=(sort_dir == "desc"))
        paged = items[skip : skip + limit]

        return {"total": total, "items": paged, "sort_by": sort_by, "sort_dir": sort_dir}

    # ---- CSV exports (Group B6 of the AppSumo launch plan) ----
    # Both files use the agreed filename format:
    #   F2F48-{kind}-{YYYY-MM-DD}-export.csv
    # which sorts cleanly by date in any file manager. UTF-8 + BOM so Excel
    # opens it correctly without manual import config. Rows are streamed via
    # a generator to keep memory flat even when the buyer list grows.
    def _csv_escape(value: Any) -> str:
        """Render any cell value as a CSV-safe string. Lists become
        pipe-separated. Dicts/None become empty strings (admin can drill down
        in the UI; the CSV is for at-a-glance snapshots, not nested data)."""
        if value is None:
            return ""
        if isinstance(value, list):
            value = "|".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = ""
        s = str(value)
        if any(ch in s for ch in (",", '"', "\n", "\r")):
            s = '"' + s.replace('"', '""') + '"'
        return s

    def _csv_row(values: list) -> str:
        return ",".join(_csv_escape(v) for v in values) + "\n"

    def _csv_filename(kind: str) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"F2F48-{kind}-{today}-export.csv"

    @api.get("/admin/buyers/export")
    async def admin_export_buyers(_admin=Depends(require_admin)):
        """Stream every buyer row as CSV. Columns are flat (no nested JSON)
        so accountants and customer-success folks can open it in Excel/Sheets
        without preprocessing. Filename: F2F48-buyers-YYYY-MM-DD-export.csv."""
        headers = [
            "email",
            "tier",
            "founder",
            "entitlements",
            "total_spend_cents",
            "renders_this_cycle",
            "render_quota_monthly",
            "avatar_renders_this_cycle",
            "avatar_sub_cap",
            "monthly_cost_cents",
            "cycle_started_at",
            "cycle_resets_at",
            "last_login_at",
            "login_count",
            "script_count",
            "shorts_count",
            "first_use_at",
            "added_at",
            "source",
            "order_id",
        ]

        async def _stream():
            # BOM so Excel auto-detects UTF-8.
            yield "\ufeff" + _csv_row(headers)
            async for b in db.buyers.find({}).sort([("addedAt", -1)]):
                row = [
                    b.get("email"),
                    b.get("tier"),
                    bool(b.get("founders")),
                    b.get("entitlements") or [],
                    b.get("totalSpendCents") or 0,
                    b.get("rendersThisCycle") or 0,
                    b.get("renderQuotaMonthly") or 0,
                    b.get("avatarRendersThisCycle") or 0,
                    b.get("avatarSubCap") or 0,
                    b.get("monthlyCostCents") or 0,
                    b.get("cycleStartedAt"),
                    b.get("cycleResetsAt"),
                    b.get("lastLoginAt"),
                    b.get("loginCount") or 0,
                    b.get("scriptCount") or 0,
                    b.get("shortsCount") or 0,
                    b.get("firstUseAt"),
                    b.get("addedAt"),
                    b.get("source"),
                    b.get("orderId"),
                ]
                yield _csv_row(row)

        return StreamingResponse(
            _stream(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{_csv_filename("buyers")}"',
            },
        )

    @api.get("/admin/usage/export")
    async def admin_export_usage(_admin=Depends(require_admin)):
        """Stream the per-customer usage leaderboard as CSV. Mirrors the
        columns of GET /admin/usage but flattened (scripts.long → scripts_long
        etc) so the CSV is one row per buyer. Filename:
        F2F48-usage-YYYY-MM-DD-export.csv."""
        from tier_config import tier_for_entitlements  # local import

        headers = [
            "email",
            "tier",
            "founder",
            "entitlements",
            "scripts_total",
            "scripts_long",
            "scripts_shorts",
            "scripts_sprint",
            "scripts_last_at",
            "renders_total",
            "renders_faceless",
            "renders_avatar",
            "renders_complete",
            "renders_failed",
            "renders_last_at",
            "spend_cents",
            "buyer_total_spend_cents",
            "login_count",
            "last_seen",
            "added_at",
        ]

        # Pre-fetch the buyer base + email set in one pass; reuse the same
        # $group aggregations the /admin/usage endpoint uses so the CSV
        # numbers match the UI table 1:1.
        buyer_docs: list[dict] = []
        async for b in db.buyers.find({}, {
            "email": 1, "entitlements": 1, "tier": 1, "founders": 1,
            "lastLoginAt": 1, "loginCount": 1, "addedAt": 1, "totalSpendCents": 1,
        }).sort([("email", 1)]):
            buyer_docs.append(b)
        emails = [b["email"] for b in buyer_docs if b.get("email")]

        async def _agg(coll, group: dict) -> dict[str, dict]:
            out: dict[str, dict] = {}
            if not emails:
                return out
            pipeline = [{"$match": {"user_email": {"$in": emails}}}, {"$group": group}]
            async for row in coll.aggregate(pipeline):
                key = row.pop("_id", None)
                if isinstance(key, str):
                    out[key] = row
            return out

        scripts_by_email = await _agg(db.scripts, {
            "_id": "$user_email",
            "total":  {"$sum": 1},
            "long":   {"$sum": {"$cond": [{"$eq": ["$mode", "long"]},   1, 0]}},
            "shorts": {"$sum": {"$cond": [{"$eq": ["$mode", "shorts"]}, 1, 0]}},
            "sprint": {"$sum": {"$cond": [{"$eq": ["$mode", "sprint"]}, 1, 0]}},
            "last_script_at": {"$max": "$created_at"},
        })
        renders_by_email = await _agg(db.renders, {
            "_id": "$user_email",
            "total":    {"$sum": 1},
            "faceless": {"$sum": {"$cond": [{"$eq": ["$mode", "faceless"]}, 1, 0]}},
            "avatar":   {"$sum": {"$cond": [{"$eq": ["$mode", "avatar"]},   1, 0]}},
            "complete": {"$sum": {"$cond": [{"$eq": ["$status", "complete"]}, 1, 0]}},
            "failed":   {"$sum": {"$cond": [{"$eq": ["$status", "failed"]},   1, 0]}},
            "spend_cents": {"$sum": {"$ifNull": ["$actual_cost_cents", 0]}},
            "last_render_at": {"$max": "$created_at"},
        })

        async def _stream():
            yield "\ufeff" + _csv_row(headers)
            for b in buyer_docs:
                email = b.get("email") or ""
                ents = list(b.get("entitlements") or [])
                tier_id = (b.get("tier") or "").strip().lower()
                if not tier_id:
                    tier_id = tier_for_entitlements(ents).id
                s = scripts_by_email.get(email, {})
                r = renders_by_email.get(email, {})
                last_seen = _iso_max(b.get("lastLoginAt"), s.get("last_script_at"))
                last_seen = _iso_max(last_seen, r.get("last_render_at"))
                if not last_seen:
                    last_seen = b.get("addedAt")
                row = [
                    email,
                    tier_id,
                    bool(b.get("founders")),
                    ents,
                    int(s.get("total")  or 0),
                    int(s.get("long")   or 0),
                    int(s.get("shorts") or 0),
                    int(s.get("sprint") or 0),
                    s.get("last_script_at"),
                    int(r.get("total")    or 0),
                    int(r.get("faceless") or 0),
                    int(r.get("avatar")   or 0),
                    int(r.get("complete") or 0),
                    int(r.get("failed")   or 0),
                    r.get("last_render_at"),
                    int(r.get("spend_cents") or 0),
                    int(b.get("totalSpendCents") or 0),
                    int(b.get("loginCount") or 0),
                    last_seen,
                    b.get("addedAt"),
                ]
                yield _csv_row(row)

        return StreamingResponse(
            _stream(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{_csv_filename("usage")}"',
            },
        )

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
        # Track which entitlements are newly granted by THIS event (used to
        # show a one-shot welcome toast on the customer's next sign-in).
        prev_ents = set((existing.get("entitlements") if existing else []) or [])
        newly_granted = sorted({product} - prev_ents)

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

        # Pending welcome toast — flagged only when this webhook ADDS at least
        # one new entitlement. auth_check reads & clears this on first sign-in
        # so the customer sees a single "Welcome — access granted" celebration.
        if newly_granted:
            set_doc["pending_welcome"] = True
            set_doc["pending_welcome_ents"] = newly_granted

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

    # ---- Direct Pinball receiver (full payload, one URL) -----------------
    @api.post("/pinball/order-completed")
    async def pinball_order_completed(
        request: Request,
        token: str = Query(...),
        # Optional fallback product — used when the payload ships NO items
        # array AND we couldn't synthesize one from top-level fields. Lets
        # legacy GHL/Kajabi/Pinball workflows that pointed at
        # `?token=X&product=base` keep working without per-funnel reconfig.
        # Matches the legacy Netlify handler's `?product=` parameter shape.
        product: str = Query("", description="Fallback entitlement if no items array"),
    ):
        """Receive the full Pinball.dev `order.completed` webhook payload at
        a SINGLE URL — no per-product query params required, no GHL forwarder
        needed. Iterates `data.items[]`, maps each `product_id` to an
        entitlement via PINBALL_PRODUCT_MAP, and grants each independently
        (line-item `id` is used as the dedupe key so partial refunds remain
        clean later). Unknown product_ids are logged as `webhook_failed` and
        skipped — the rest of the items still process.

        Fallback chain when `items[]` is empty:
          1. Try to synthesize a single item from top-level product_id/productId.
          2. If still empty, use the ?product= query param (legacy mode).
          3. If both miss, return 400 + log payload for triage.
        """
        # 1) Token gate
        if not PINBALL_WEBHOOK_TOKEN or token != PINBALL_WEBHOOK_TOKEN:
            try:
                body = await request.json()
            except Exception:
                body = {"_raw": (await request.body()).decode("utf-8", "replace")[:1000]}
            await log_activity(
                "webhook_failed",
                "",
                {"reason": "invalid token", "payload": body, "source": "pinball-direct"},
            )
            raise HTTPException(status_code=401, detail="Invalid token")

        # 2) Parse
        try:
            body = await request.json()
        except Exception:
            await log_activity(
                "webhook_failed",
                "",
                {"reason": "malformed json", "source": "pinball-direct"},
            )
            raise HTTPException(status_code=400, detail="Malformed JSON")

        # Parse the FULL Pinball payload. The Pinball workflow may fire under
        # several different shapes (raw checkout, OTO, replay, etc.) — extract
        # email/items via the lenient helpers so we match every shape the
        # legacy Netlify handler accepted. The original strict
        # `data.customer.email`-only check rejected real Pinball traffic
        # where the email lived at `customer.email` or `email`.
        email = _extract_email(body)
        items = _extract_items(body)

        if not email:
            # Log a fingerprint of the top-level keys to help debug new
            # payload shapes without exposing PII in the activity stream.
            await log_activity(
                "webhook_failed",
                "",
                {"reason": "missing customer.email",
                 "top_keys": sorted(list(body.keys()))[:20] if isinstance(body, dict) else [],
                 "payload": body, "source": "pinball-direct"},
            )
            raise HTTPException(status_code=400, detail="Missing customer email in payload")

        # 3) Items fallback chain — keep this path forgiving so GHL/Pinball/
        # Kajabi workflows don't have to ship a perfect items[] structure.
        # `fallback_mode` is stamped onto the activity log entry below so
        # admins can see WHICH path matched on the buyers screen.
        fallback_mode: Optional[str] = None
        if not items:
            synthesized = _synthesize_single_item(body)
            if synthesized:
                items = [synthesized]
                fallback_mode = "synthesized_single_item"
            elif product:
                # Legacy mode: grant the entitlement named in the ?product=
                # query param, no per-product mapping required. Matches the
                # Netlify handler's behavior so old funnels keep working.
                if product in KNOWN_ENTITLEMENTS:
                    items = [{
                        "id": _extract_order_id(body) or "",
                        "product_id": f"__fallback_query_param__:{product}",
                        "product_name": f"Fallback ({product})",
                        "amount": _extract_order_total_cents(body),
                        "_fallback_entitlement": product,
                    }]
                    fallback_mode = "query_param_product"
                else:
                    await log_activity(
                        "webhook_failed",
                        email,
                        {"reason": f"unknown query-param product '{product}'",
                         "payload": body, "source": "pinball-direct"},
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unknown product in query param: {product}",
                    )

        if not items:
            await log_activity(
                "webhook_failed",
                email,
                {"reason": "no items in payload (no items[] AND no top-level product_id AND no ?product= query)",
                 "top_keys": sorted(list(body.keys()))[:20] if isinstance(body, dict) else [],
                 "payload": body, "source": "pinball-direct"},
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "No items in payload. Add an items[] array, a top-level "
                    "product_id, or include ?product=base in the webhook URL."
                ),
            )

        # 3) Iterate items, grant per product_id
        results: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            product_id = (item.get("product_id") or "").strip()
            # Synthesized + query-param fallbacks ship `_fallback_entitlement`
            # directly so we skip the PINBALL_PRODUCT_MAP lookup (the
            # product_id is a synthetic sentinel like
            # `__fallback_query_param__:base` that wouldn't be in the map).
            entitlement = item.get("_fallback_entitlement") or PINBALL_PRODUCT_MAP.get(product_id)
            line_item_id = (item.get("id") or "").strip()
            amount = item.get("amount") or 0

            if not entitlement:
                await log_activity(
                    "webhook_failed",
                    email,
                    {
                        "reason": "unmapped product_id",
                        "product_id": product_id,
                        "product_name": item.get("product_name"),
                        "item": item,
                        "source": "pinball-direct",
                    },
                )
                results.append({"product_id": product_id, "status": "unmapped"})
                continue

            try:
                result = await _process_pinball_event(
                    product=entitlement,
                    body={
                        "email": email,
                        "total_amount": str(amount),
                        "order_id": line_item_id,
                    },
                    source="pinball-direct",
                )
                results.append({
                    "product_id": product_id,
                    "entitlement": entitlement,
                    **result,
                })
            except HTTPException as exc:
                results.append({
                    "product_id": product_id,
                    "entitlement": entitlement,
                    "status": "error",
                    "detail": exc.detail,
                })

        ok_count = sum(1 for r in results if r.get("status") == "ok")
        dup_count = sum(1 for r in results if r.get("status") == "duplicate")
        unmapped_count = sum(1 for r in results if r.get("status") == "unmapped")
        return {
            "ok": True,
            "email": email,
            "items_processed": len(results),
            "granted": ok_count,
            "duplicates": dup_count,
            "unmapped": unmapped_count,
            "fallback_mode": fallback_mode,  # null when normal items[] path
            "results": results,
        }

    return {"process_pinball_event": _process_pinball_event}
