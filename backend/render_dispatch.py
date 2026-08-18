"""Signed, event-driven dispatch helpers for isolated Faceless renders."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


SIGNATURE_HEADER = "X-F48-Signature"
TIMESTAMP_HEADER = "X-F48-Timestamp"


def canonical_dispatch_body(job_id: str) -> bytes:
    return json.dumps(
        {"job_id": job_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def dispatch_signature(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_dispatch_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    *,
    now: int | None = None,
    max_age_s: int = 300,
) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - sent_at) > max_age_s:
        return False
    expected = dispatch_signature(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


def recovery_query(*, now: datetime | None = None, redispatch_after_s: int = 300) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    cutoff = (current - timedelta(seconds=redispatch_after_s)).isoformat()
    return {
        "status": "queued",
        "mode": "faceless",
        "$and": [
            {
                "$or": [
                    {"worker_execution_id": {"$exists": False}},
                    {"worker_execution_id": None},
                ]
            },
            {
                "$or": [
                    {"dispatch_last_accepted_at": {"$exists": False}},
                    {"dispatch_last_accepted_at": {"$lte": cutoff}},
                ]
            },
        ],
    }


async def dispatch_render_job(
    job_id: str,
    *,
    url: str,
    secret: str,
    timeout_s: float = 10.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    body = canonical_dispatch_body(job_id)
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: dispatch_signature(secret, timestamp, body),
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await http.post(url, content=body, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"accepted": True}
    finally:
        if owns_client:
            await http.aclose()
