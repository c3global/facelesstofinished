"""KIE.ai webhook callback route.

KIE delivers task completion via a POST with HMAC-signed headers:
  * X-Webhook-Timestamp: unix seconds
  * X-Webhook-Signature: Base64(HMAC-SHA256(task_id + "." + timestamp, KIE_WEBHOOK_HMAC_KEY))

The webhook is idempotent by design — every callback updates the same
``db.kie_tasks`` document keyed by ``task_id``. Duplicate deliveries
land as identical writes.

Configuration:
  * KIE_WEBHOOK_HMAC_KEY — HMAC secret from KIE Settings. Required.
  * KIE_WEBHOOK_TIMESTAMP_WINDOW_S — replay window in seconds (default
    300s). KIE doesn't publish an authoritative window; this is our
    self-imposed replay guard, tunable via env once we observe real
    delivery behavior.

The route is mounted from server.py via ``register_kie_callback(app, db)``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)

KIE_WEBHOOK_TIMESTAMP_WINDOW_S = int(os.environ.get("KIE_WEBHOOK_TIMESTAMP_WINDOW_S", "300"))


def verify_kie_signature(
    task_id: str,
    timestamp: str,
    received_signature: str,
    hmac_key: str,
) -> bool:
    """Verify a KIE webhook signature using constant-time comparison.

    Contract (KIE docs, 2026-08-15):
      message   = task_id + "." + timestamp
      signature = Base64(HMAC-SHA256(message, hmac_key))
    """
    if not (task_id and timestamp and received_signature and hmac_key):
        return False
    message = f"{task_id}.{timestamp}".encode("utf-8")
    digest = hmac.new(hmac_key.encode("utf-8"), message, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, received_signature)


def _check_timestamp_window(timestamp_str: str, window_s: int) -> Optional[str]:
    """Return None when within window, else a human error string."""
    try:
        ts = int(timestamp_str)
    except (TypeError, ValueError):
        return "invalid_timestamp"
    delta = abs(int(time.time()) - ts)
    if delta > window_s:
        return f"stale_webhook_{delta}s"
    return None


def build_router(db: Any) -> APIRouter:
    """Return a FastAPI APIRouter that mounts the KIE callback.

    ``db`` is passed in so tests can supply an in-memory stub without
    importing the live MongoDB client.
    """
    router = APIRouter()

    @router.post("/kie/webhook")
    async def kie_webhook(
        request: Request,
        x_webhook_timestamp: Optional[str] = Header(default=None),
        x_webhook_signature: Optional[str] = Header(default=None),
    ) -> dict[str, Any]:
        # Read body EXACTLY ONCE and only if headers are plausibly valid.
        # We don't log the body or headers to avoid leaking sensitive
        # payloads via stdout / log aggregation.
        hmac_key = os.environ.get("KIE_WEBHOOK_HMAC_KEY", "")
        if not hmac_key:
            # Callback not configured — respond 503 so KIE will retry
            # once we've set the key rather than dropping the delivery.
            raise HTTPException(503, "webhook not configured")

        if not (x_webhook_timestamp and x_webhook_signature):
            raise HTTPException(401, "missing webhook headers")

        stale = _check_timestamp_window(x_webhook_timestamp, KIE_WEBHOOK_TIMESTAMP_WINDOW_S)
        if stale is not None:
            raise HTTPException(401, stale)

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "invalid json")

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise HTTPException(400, "missing data block")
        task_id = (data.get("task_id") or data.get("taskId") or "").strip()
        if not task_id:
            raise HTTPException(400, "missing task_id")

        if not verify_kie_signature(task_id, x_webhook_timestamp, x_webhook_signature, hmac_key):
            # Deliberately vague message so the response body doesn't
            # tell an attacker whether the task_id was recognized.
            raise HTTPException(401, "invalid signature")

        # Persist. Idempotent by design (task_id primary key).
        state = (data.get("state") or "").lower()
        record = {
            "task_id": task_id,
            "state": state,
            "code": body.get("code") if isinstance(body, dict) else None,
            "updated_at": time.time(),
            "callback_data": {
                # Store only a bounded subset — same set the KIE provider
                # uses so we don't over-persist.
                k: data.get(k)
                for k in ("state", "resultJson", "costTime", "creditsConsumed", "failCode", "failMsg", "completeTime")
                if k in data
            },
        }
        try:
            await db.kie_tasks.update_one(
                {"task_id": task_id},
                {"$set": record},
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[kie] webhook persist failed for %s: %s", task_id, type(exc).__name__)
            # Don't 500 — KIE will retry, and the poll fallback will
            # still pick up the completion.
            return {"ok": False, "reason": "persist_failed"}

        return {"ok": True}

    return router


__all__ = [
    "build_router",
    "verify_kie_signature",
    "KIE_WEBHOOK_TIMESTAMP_WINDOW_S",
]
