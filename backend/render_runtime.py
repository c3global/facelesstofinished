"""Small, testable safeguards shared by Studio render workers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone


RENDER_QUEUE_LOCK_ID = "faceless48-render-queue"


def stale_render_query(cutoff_iso: str) -> dict:
    """Match every non-terminal job whose worker heartbeat is stale."""
    return {
        # A queued job has not started and therefore has no worker heartbeat.
        # Reaping it as "stuck" would incorrectly fail valid backlog items.
        "status": {"$nin": ["queued", "complete", "failed"]},
        "$or": [
            {"updated_at": {"$lt": cutoff_iso}},
            {
                "updated_at": {"$exists": False},
                "created_at": {"$lt": cutoff_iso},
            },
            {
                "updated_at": {"$exists": False},
                "created_at": {"$exists": False},
            },
        ],
    }


def lease_expiry_iso(*, seconds: int, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return (current + timedelta(seconds=seconds)).isoformat()


def worker_lock_query(execution_id: str, *, now_iso: str) -> dict:
    """Acquire an absent/expired lease, or renew one already owned by us."""
    return {
        "_id": RENDER_QUEUE_LOCK_ID,
        "$or": [
            {"lease_expires_at": {"$lt": now_iso}},
            {"owner": execution_id},
        ],
    }


def worker_lock_update(execution_id: str, *, lease_expires_at: str, now_iso: str) -> dict:
    return {
        "$set": {
            "owner": execution_id,
            "lease_expires_at": lease_expires_at,
            "heartbeat_at": now_iso,
        },
    }


def queued_render_query(modes: tuple[str, ...] = ("faceless",)) -> dict:
    return {
        "status": "queued",
        "mode": {"$in": list(modes)},
        "$or": [
            {"worker_execution_id": {"$exists": False}},
            {"worker_execution_id": None},
        ],
    }


async def communicate_process_with_timeout(
    process,
    *,
    timeout_s: float,
) -> tuple[bytes, bytes]:
    """Wait for a child process and guarantee a timed-out child is reaped."""
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass  # Child exited between the timeout and kill attempt.
        await process.communicate()
        raise
    except asyncio.CancelledError:
        # An outer scene timeout cancels this coroutine.  Previously that
        # cancellation skipped the timeout handler above and left ffmpeg
        # running in the background.  On the 512 MB production container,
        # subsequent scenes could accumulate orphaned ffmpeg children until
        # the backend was OOM-killed at 55%.
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.shield(process.communicate())
        except Exception:
            pass
        raise
