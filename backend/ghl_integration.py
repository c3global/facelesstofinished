"""GoHighLevel (GHL) outbound integration.

Charity's CRM-of-record is GHL (NOT Resend, NOT Mailchimp). When a new buyer
lands — either via the Pinball webhook (paid purchase) or via the AppSumo
license redemption flow — we want to push their contact + tier into GHL
so her automations (welcome sequence, onboarding emails, in-app nudges,
tier-specific upsells) fire automatically.

Design choice: **Inbound Webhook**, NOT the full GHL REST API.

GHL Workflows can ingest a custom JSON POST on an "Inbound Webhook" trigger
node — the user pastes the resulting webhook URL into our `GHL_WEBHOOK_URL`
env var. We send a flat, predictable payload. GHL's workflow handles
contact upsert + tagging + sequence enrollment on their side. This means:

  • Zero OAuth dance, zero per-location ID juggling.
  • Charity owns the field mapping and tag taxonomy in her own workspace.
  • Provider outages don't crash our app — push is fire-and-forget.

If `GHL_WEBHOOK_URL` is empty (default — preview / local dev), this module
no-ops silently. Failures are logged to `db.activity` with `type =
'ghl_push_failed'` so admins can replay manually from the admin UI later.

Payload schema (stable, additive only):

    {
      "email":         "user@example.com",
      "tier_id":       "pro_plus" | "founder" | "studio" | ...,
      "tier_label":    "Pro Plus" | "Founder" | ...,
      "source":        "pinball_purchase" | "appsumo_redemption" | "manual",
      "tags":          ["F2F48-customer", "tier:pro_plus", "source:appsumo"],
      "metadata":      { order_id?, code?, founder?, spend_cents? },
      "occurred_at":   "2026-06-30T11:55:00+00:00",
      "app":           "F2F48"
    }
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config — these env vars are READ AT CALL TIME, not at import time. Lets
# the agent flip the kill switch by editing `.env` and restarting backend
# without touching code.
# ---------------------------------------------------------------------------

def _webhook_url() -> str:
    return (os.environ.get("GHL_WEBHOOK_URL") or "").strip()


def _auth_header() -> str:
    """Optional extra auth header (some GHL workflows require a shared secret
    on top of the obscure webhook URL). Format: `Header-Name: header-value`."""
    return (os.environ.get("GHL_WEBHOOK_AUTH_HEADER") or "").strip()


def is_configured() -> bool:
    return bool(_webhook_url())


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _tags_for(tier_id: str, source: str, founder: bool) -> list[str]:
    """Stable, lowercase, kebab-style tags that Charity can filter on in GHL.
    Adding new tags here is safe (additive). NEVER remove or rename — GHL
    workflows in the field already filter on these strings."""
    tags = ["f2f48-customer", f"tier:{tier_id}", f"source:{source}"]
    if founder:
        tags.append("founder")
    return tags


def build_payload(
    *,
    email: str,
    tier_id: str,
    tier_label: str,
    source: str,
    founder: bool = False,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "email": (email or "").strip().lower(),
        "tier_id": tier_id,
        "tier_label": tier_label,
        "source": source,
        "tags": _tags_for(tier_id, source, founder),
        "metadata": metadata or {},
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "app": "F2F48",
    }


# ---------------------------------------------------------------------------
# Push — fire-and-forget. Never raises into the calling request handler.
# Activity logger is injected (avoid circular import on admin_routes).
# ---------------------------------------------------------------------------

async def push(
    payload: dict[str, Any],
    *,
    log_activity: Optional[Callable[[str, str, dict[str, Any]], Awaitable[None]]] = None,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
    """POST the payload to the configured GHL inbound webhook. Returns a
    small status dict so callers (e.g. admin replay) can surface success/
    failure to the operator. Buyer-facing call sites should ignore the
    return value — this is fire-and-forget by design."""
    url = _webhook_url()
    if not url:
        return {"status": "skipped", "reason": "GHL_WEBHOOK_URL not configured"}

    headers = {"Content-Type": "application/json", "User-Agent": "F2F48/1.0"}
    extra = _auth_header()
    if extra and ":" in extra:
        name, value = extra.split(":", 1)
        headers[name.strip()] = value.strip()

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(url, json=payload, headers=headers)
        ok = 200 <= r.status_code < 300
        result = {
            "status": "ok" if ok else "failed",
            "http_status": r.status_code,
            "response_excerpt": (r.text or "")[:200],
        }
        if not ok and log_activity is not None:
            try:
                await log_activity(
                    "ghl_push_failed",
                    payload.get("email", ""),
                    {"http_status": r.status_code, "payload": payload, "response": (r.text or "")[:500]},
                )
            except Exception:
                pass  # never let telemetry breakage propagate
        return result
    except Exception as exc:
        logger.warning("[ghl] push failed: %s: %s", type(exc).__name__, exc)
        if log_activity is not None:
            try:
                await log_activity(
                    "ghl_push_failed",
                    payload.get("email", ""),
                    {"error": f"{type(exc).__name__}: {exc}", "payload": payload},
                )
            except Exception:
                pass
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def push_in_background(
    payload: dict[str, Any],
    *,
    log_activity: Optional[Callable[[str, str, dict[str, Any]], Awaitable[None]]] = None,
) -> None:
    """Schedule a non-blocking push. Used in request handlers (signup,
    redemption) where blocking on GHL would hurt UX. The Task is fired and
    immediately abandoned — its outcome is recorded into activity if it
    fails."""
    if not is_configured():
        return
    try:
        asyncio.create_task(push(payload, log_activity=log_activity))
    except RuntimeError:
        # No running event loop — extremely rare path (only happens when
        # called outside an async context, e.g. during module import).
        # Silently skip — the next live request will catch up.
        pass


# ---------------------------------------------------------------------------
# Magic-link email push — fires when a user requests a sign-in link.
# Payload shape is distinct from the buyer-lifecycle push so Charity's
# GHL workflows can filter on `event == "magic_link_requested"` and route
# the send through her transactional-email node.
# ---------------------------------------------------------------------------

def build_magic_link_payload(
    *,
    email: str,
    magic_link_url: str,
    expires_at_iso: str,
    ttl_minutes: int,
) -> dict[str, Any]:
    return {
        "event": "magic_link_requested",
        "email": (email or "").strip().lower(),
        "magic_link_url": magic_link_url,
        "expires_at": expires_at_iso,
        "ttl_minutes": ttl_minutes,
        "tags": ["f2f48-customer", "event:magic-link"],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "app": "F2F48",
    }


async def push_magic_link(
    *,
    email: str,
    magic_link_url: str,
    expires_at_iso: str,
    ttl_minutes: int,
    log_activity: Optional[Callable[[str, str, dict[str, Any]], Awaitable[None]]] = None,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
    """Send the magic-link payload to GHL synchronously (short timeout).

    Runs synchronously (not fire-and-forget) so the /auth/request-magic-link
    handler can surface a friendly error if the GHL workflow is
    misconfigured — the user needs to know their email won't arrive.
    """
    payload = build_magic_link_payload(
        email=email,
        magic_link_url=magic_link_url,
        expires_at_iso=expires_at_iso,
        ttl_minutes=ttl_minutes,
    )
    return await push(payload, log_activity=log_activity, timeout_s=timeout_s)
