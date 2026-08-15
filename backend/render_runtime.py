"""Small, testable safeguards shared by Studio render workers."""
from __future__ import annotations

import asyncio


def stale_render_query(cutoff_iso: str) -> dict:
    """Match every non-terminal job whose worker heartbeat is stale."""
    return {
        "status": {"$nin": ["complete", "failed"]},
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
