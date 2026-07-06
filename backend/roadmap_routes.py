"""Roadmap routes — public GET + admin-gated POST/PATCH/DELETE.

The public Roadmap page at /roadmap reads from this single source of truth.
Admins can edit inline directly on the page (add item, edit text, reorder,
delete) — every write checks admin status server-side, not just UI hiding.

Storage:
  - Mongo collection: `roadmap_items`
  - On first GET (collection empty), seeds from `_default_items()` so the
    page never renders blank even before an admin has touched it.

Item shape:
  {
    id: str,                  # uuid4 hex, generated server-side
    column: str,              # "shipped" | "inProgress" | "planned" | "considering"
    title: str,
    blurb: str,
    tag: Optional[str],       # "TOP REQUEST" | "P0" | "APPSUMO" | "PRO PLUS" | "THIS WEEK" | ...
    order: int,               # within-column sort key (smaller = top)
    created_at: iso8601 str,
    updated_at: iso8601 str,
  }
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import hashlib

from fastapi import Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("f48.roadmap")

VALID_COLUMNS = ("shipped", "inProgress", "planned", "considering")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_items() -> list[dict]:
    """Seed used on first /api/roadmap GET if the collection is empty.
    Mirrors the curated copy Charity approved in iter 44 + adds the 7
    items from the GPT brain-dump (Script Revision Tools as TOP REQUEST,
    Brand Voice Profiles, Authority Content Templates, Content Series
    Builder in Planned + Approval Workflow, Multilingual Scripts, Agency
    / White-label in Considering).
    Canva integration stays at the top of Planned per Charity's ask.
    """
    now = _now_iso()
    items: list[dict] = []

    def add(column: str, title: str, blurb: str, tag: Optional[str] = None) -> None:
        items.append({
            "id": uuid.uuid4().hex,
            "column": column,
            "title": title,
            "blurb": blurb,
            "tag": tag,
            "order": len([i for i in items if i["column"] == column]),
            "created_at": now,
            "updated_at": now,
        })

    # ---- Shipped (8) ----
    add("shipped", "Script Engine",
        "Long-form, Shorts, and Sprint modes. Generate 3 platform-tuned scripts at once with side-by-side compare view.")
    add("shipped", "Studio — Avatar mode",
        "Talking-head videos in 16:9 or 9:16 with burned-in captions. Browse 1,200+ avatars and 2,300+ voices.")
    add("shipped", "Studio — Faceless mode",
        "Slideshow-style videos with AI voiceover, stock B-roll from Pexels and Pixabay, and AI-generated stills via Gemini Nano Banana for scenes where stock doesn't fit. Optional caption burn-in.")
    add("shipped", "Thumbnail Engine",
        "Two engines (Premium + Fast), three aspect ratios, prompt rewriter, full-screen preview, batch-generate from any script.")
    add("shipped", "Bring Your Own Keys (BYOK)",
        "Pro Plus + Founders can plug in their own Anthropic, OpenAI, Google, ElevenLabs, HeyGen, and fal.ai keys. Encrypted at rest.",
        tag="Pro Plus")
    add("shipped", "Admin Dashboard",
        "Usage leaderboard, customer drilldown, activity feed, license management, CSV exports. For the team only.")
    add("shipped", "Light + Dark themes",
        "Switch in the header. Every page, every card, every chip — polished to readable contrast in both modes.")
    add("shipped", "Redemption codes",
        "Paste your code, instantly unlock your tier. Works from the footer, the login screen, or your profile dropdown.")

    # ---- In Progress (2) ----
    add("inProgress", "Production launch",
        "Final pre-launch hardening — Fernet-encrypted BYOK vault, deploy health checks, last QA pass on captioned Faceless renders.",
        tag="This week")
    add("inProgress", "GoHighLevel CRM sync",
        "Auto-push every new customer + redemption to your GHL pipeline so onboarding sequences fire the moment someone joins.")

    # ---- Planned (13) — Canva first (TOP REQUEST), then GPT additions ----
    add("planned", "Canva integration",
        "One-click export your thumbnails into a new Canva design so you can layer your branded text, logo, and overlays without leaving the workflow.",
        tag="Top request")
    add("planned", "Script Revision Tools",
        "One-click refine: shorten, expand, strengthen the hook, make it more conversational, soften the tone, or sharpen the call-to-action.",
        tag="Top request")
    add("planned", "Brand Voice Profiles",
        "Save your tone, terminology, audience, and signature phrases once. Every script auto-tunes to that profile — no more re-prompting from scratch.")
    add("planned", "Authority Content Templates",
        "Pre-built script structures for the off-camera expert: lead magnet promo, webinar driver, expert commentary, offer explainer, objection handler, thought leadership.")
    add("planned", "Content Series Builder",
        "Turn one topic into a 5-part series with built-in narrative arc — perfect for content factories and authority funnels.")
    add("planned", "Cinematic Faceless (true text-to-video)",
        "Upgrade Faceless mode from static-image slideshows to real motion video. Targeting Veo, Pika, or Kling — whichever ships the best 9:16 quality.",
        tag="P0")
    add("planned", "Upload your own B-roll",
        "Drop in your own video clips per scene instead of relying on stock. Mix-and-match with AI-generated visuals.")
    add("planned", "Record your own voiceover",
        "Browser mic recorder built into the Voice picker. Skip the AI voice entirely when you want your real voice.")
    add("planned", "Brand kits",
        "Save your colors, fonts, and logo once — they auto-apply to every thumbnail and on-screen text caption.")
    add("planned", "Bulk script-to-video (CSV upload)",
        "Paste in 50 topics, walk away, come back to 50 rendered videos. Built for content factories.")
    add("planned", "AI music selection",
        "Smart background music picker that matches the mood, pace, and platform of each script — no more royalty-free hunting.")
    add("planned", "Native publishing",
        "Render → publish straight to YouTube, TikTok, Instagram Reels, and YouTube Shorts. Schedule or post immediately.")
    add("planned", "Performance analytics",
        "After you publish, pull views, watch-time, and engagement back into the dashboard. See which scripts and thumbnails actually convert.")

    # ---- Considering (8) ----
    add("considering", "Voice cloning",
        "Clone your own voice via ElevenLabs so every Faceless render sounds like you, not a generic AI narrator.")
    add("considering", "Team seats",
        "Multi-user workspaces — invite editors, give roles, share script + render libraries.")
    add("considering", "Approval Workflow",
        "Review notes, approval status, and version history for consultants and agencies producing on behalf of clients.")
    add("considering", "Multilingual Scripts",
        "Generate or translate scripts in 10+ languages — opens up international markets for global professionals.")
    add("considering", "Agency / White-label",
        "Client portals, your-branding-instead-of-ours, multi-brand dashboards. Built for the consultants who resell this to their book.")
    add("considering", "Webhook + Zapier outbound",
        "Fire a webhook every time a render completes so your downstream tools (Notion, Airtable, Slack, etc.) get notified.")
    add("considering", "Avatar background removal",
        "Drop in your own background behind any HeyGen avatar — your brand setting, b-roll, motion graphics, anything.")
    add("considering", "Mobile app",
        "Native iOS + Android apps for reviewing renders, copying scripts, and approving thumbnails on the go.")

    return items


def _strip_id(doc: dict) -> dict:
    if doc and "_id" in doc:
        return {k: v for k, v in doc.items() if k != "_id"}
    return doc or {}


def _voter_id_for_request(request: Request | None) -> str:
    """Stable per-visitor hash used to dedupe roadmap +1 votes.

    Anonymous voting keeps the roadmap open to AppSumo reviewers who
    aren't signed in yet. We fingerprint on (IP + user-agent) so a
    single laptop can't spam votes just by hitting the button 50 times,
    while still not requiring auth. A VPN hop resets the hash — good
    enough for a directional signal, not a binding poll.
    """
    if request is None:
        return "anon"
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:200]
    return hashlib.sha256(f"{ip}|{ua}".encode("utf-8")).hexdigest()[:24]


def _decorate_item_for_public(doc: dict, voter_id: str) -> dict:
    """Strip Mongo _id + voter_hashes list (never sent to client), and
    surface `votes` (int) and `has_voted` (bool) so the UI can render
    the +1 button state without a second round-trip."""
    d = _strip_id(doc)
    voters = d.pop("voter_hashes", []) or []
    d["votes"] = int(d.get("votes") or 0)
    d["has_voted"] = voter_id in voters
    return d


class RoadmapItemCreate(BaseModel):
    column: str = Field(..., description='one of shipped/inProgress/planned/considering')
    title: str = Field(..., min_length=1, max_length=120)
    blurb: str = Field(..., min_length=1, max_length=600)
    tag: Optional[str] = Field(None, max_length=40)


class RoadmapItemUpdate(BaseModel):
    column: Optional[str] = None
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    blurb: Optional[str] = Field(None, min_length=1, max_length=600)
    tag: Optional[str] = Field(None, max_length=40)
    order: Optional[int] = None


def register_roadmap_routes(*, api, db, current_user, ADMIN_EMAILS):
    """Mount /api/roadmap* (public GET) and /api/admin/roadmap* (admin write)."""

    async def require_admin(user=Depends(current_user)):
        if not (user.is_admin or user.email.lower() in ADMIN_EMAILS):
            raise HTTPException(status_code=403, detail="Admin only")
        return user

    async def _ensure_seed():
        """Insert the default roadmap items on first read if collection is empty."""
        count = await db.roadmap_items.count_documents({})
        if count == 0:
            seed = _default_items()
            if seed:
                await db.roadmap_items.insert_many(seed)
                logger.info("[roadmap] seeded %d default items", len(seed))

    # ---- Public read ----
    @api.get("/roadmap")
    async def get_roadmap(request: Request):
        """Return the full roadmap grouped by column. Public — no auth.
        Seeds default items on first call so the page never renders blank.
        Also stamps `votes` + `has_voted` on every item so the +1 UI can
        render instantly without a second call."""
        await _ensure_seed()
        voter_id = _voter_id_for_request(request)
        items_by_col: dict[str, list[dict]] = {c: [] for c in VALID_COLUMNS}
        async for doc in db.roadmap_items.find({}).sort([("column", 1), ("order", 1)]):
            col = doc.get("column")
            if col not in items_by_col:
                continue
            items_by_col[col].append(_decorate_item_for_public(doc, voter_id))
        return {
            "columns": [
                {"key": "shipped", "label": "Shipped",
                 "note": "Already live and working for every buyer.",
                 "items": items_by_col["shipped"]},
                {"key": "inProgress", "label": "In Progress",
                 "note": "Actively being built right now.",
                 "items": items_by_col["inProgress"]},
                {"key": "planned", "label": "Planned",
                 "note": "Committed next. We don't promise dates — we promise these will ship.",
                 "items": items_by_col["planned"]},
                {"key": "considering", "label": "Considering",
                 "note": "On our radar. Tell us which one matters most — the loudest demand moves up to Planned.",
                 "items": items_by_col["considering"]},
            ],
        }

    # ---- Admin write ----
    @api.post("/admin/roadmap/items")
    async def create_item(payload: RoadmapItemCreate, admin=Depends(require_admin)):
        if payload.column not in VALID_COLUMNS:
            raise HTTPException(status_code=400, detail=f"column must be one of {VALID_COLUMNS}")
        # Append to end of the column (highest existing order + 1).
        last = await db.roadmap_items.find_one(
            {"column": payload.column}, sort=[("order", -1)],
        )
        order = (int(last.get("order", 0)) + 1) if last else 0
        doc = {
            "id": uuid.uuid4().hex,
            "column": payload.column,
            "title": payload.title.strip(),
            "blurb": payload.blurb.strip(),
            "tag": (payload.tag or "").strip() or None,
            "order": order,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.roadmap_items.insert_one(doc)
        return _strip_id(doc)

    @api.patch("/admin/roadmap/items/{item_id}")
    async def update_item(
        payload: RoadmapItemUpdate,
        item_id: str = Path(...),
        admin=Depends(require_admin),
    ):
        existing = await db.roadmap_items.find_one({"id": item_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Item not found")
        upd: dict = {"updated_at": _now_iso()}
        if payload.column is not None:
            if payload.column not in VALID_COLUMNS:
                raise HTTPException(status_code=400, detail=f"column must be one of {VALID_COLUMNS}")
            upd["column"] = payload.column
        if payload.title is not None:
            upd["title"] = payload.title.strip()
        if payload.blurb is not None:
            upd["blurb"] = payload.blurb.strip()
        if payload.tag is not None:
            # empty string explicitly clears the tag (null in mongo)
            upd["tag"] = payload.tag.strip() or None
        if payload.order is not None:
            upd["order"] = int(payload.order)
        await db.roadmap_items.update_one({"id": item_id}, {"$set": upd})
        doc = await db.roadmap_items.find_one({"id": item_id})
        return _strip_id(doc or {})

    @api.delete("/admin/roadmap/items/{item_id}")
    async def delete_item(item_id: str = Path(...), admin=Depends(require_admin)):
        r = await db.roadmap_items.delete_one({"id": item_id})
        if r.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"ok": True}

    @api.post("/admin/roadmap/reorder")
    async def reorder(
        payload: dict = Body(...),
        admin=Depends(require_admin),
    ):
        """Persist a new within-column order. Payload shape:
          { "column": "planned", "ids": ["<id1>", "<id2>", ...] }
        Items in `ids` get order=0..N. Items NOT in the list keep their
        current order (no-op). Cross-column moves go through PATCH; this
        endpoint is reorder-within-column only."""
        column = (payload.get("column") or "").strip()
        ids = payload.get("ids") or []
        if column not in VALID_COLUMNS:
            raise HTTPException(status_code=400, detail=f"column must be one of {VALID_COLUMNS}")
        if not isinstance(ids, list) or not ids:
            raise HTTPException(status_code=400, detail="ids must be a non-empty array")
        for i, item_id in enumerate(ids):
            await db.roadmap_items.update_one(
                {"id": item_id, "column": column},
                {"$set": {"order": i, "updated_at": _now_iso()}},
            )
        return {"ok": True, "updated": len(ids)}

    # ---- Public +1 vote (Planned + Considering only) ----
    @api.post("/roadmap/items/{item_id}/vote")
    async def vote_item(request: Request, item_id: str = Path(...)):
        """Anonymous +1 vote. Enforced dedup per (IP + user-agent) hash
        via `$addToSet` so a second click from the same fingerprint is
        a no-op. Only Planned + Considering items accept votes — the
        Shipped and In Progress columns don't need a signal."""
        voter_id = _voter_id_for_request(request)
        existing = await db.roadmap_items.find_one({"id": item_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Item not found")
        if existing.get("column") not in ("planned", "considering"):
            raise HTTPException(status_code=400, detail="Votes only apply to Planned or Considering items")
        # Atomic: increment votes ONLY if the voter isn't already in the set.
        result = await db.roadmap_items.find_one_and_update(
            {"id": item_id, "voter_hashes": {"$ne": voter_id}},
            {"$inc": {"votes": 1},
             "$addToSet": {"voter_hashes": voter_id},
             "$set": {"updated_at": _now_iso()}},
            return_document=True,  # ReturnDocument.AFTER on motor
        )
        if result is None:
            # Voter already in set — return current count without incrementing.
            return {"votes": int(existing.get("votes") or 0), "has_voted": True, "already_voted": True}
        return {"votes": int(result.get("votes") or 0), "has_voted": True, "already_voted": False}

    @api.post("/admin/roadmap/reseed")
    async def reseed(admin=Depends(require_admin)):
        """Nuke and reseed with defaults — emergency button. Use with care."""
        deleted = (await db.roadmap_items.delete_many({})).deleted_count
        seed = _default_items()
        if seed:
            await db.roadmap_items.insert_many(seed)
        return {"ok": True, "deleted": deleted, "inserted": len(seed)}
