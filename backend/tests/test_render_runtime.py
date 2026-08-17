import asyncio

import pytest

from datetime import datetime, timezone

from render_runtime import (
    communicate_process_with_timeout,
    lease_expiry_iso,
    queued_render_query,
    stale_render_query,
    worker_lock_query,
    worker_lock_update,
)


def test_stale_query_covers_visuals_and_future_nonterminal_statuses():
    query = stale_render_query("2026-08-14T11:55:00+00:00")

    # Regression: v1.20.9 used status="visuals" at 55-69%, but the reaper's
    # old allowlist omitted it. A terminal denylist covers it automatically.
    assert query["status"] == {"$nin": ["queued", "complete", "failed"]}
    assert query["$or"][0] == {
        "updated_at": {"$lt": "2026-08-14T11:55:00+00:00"},
    }


def test_queue_and_lock_queries_are_serial_and_faceless_only():
    assert queued_render_query() == {
        "status": "queued",
        "mode": {"$in": ["faceless"]},
        "$or": [
            {"worker_execution_id": {"$exists": False}},
            {"worker_execution_id": None},
        ],
    }
    assert worker_lock_query("exec-1", now_iso="2026-08-17T12:00:00+00:00") == {
        "_id": "faceless48-render-queue",
        "$or": [
            {"lease_expires_at": {"$lt": "2026-08-17T12:00:00+00:00"}},
            {"owner": "exec-1"},
        ],
    }


def test_lock_update_has_expiring_heartbeat():
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    expiry = lease_expiry_iso(seconds=180, now=now)
    assert expiry == "2026-08-17T12:03:00+00:00"
    assert worker_lock_update(
        "exec-1", lease_expires_at=expiry, now_iso=now.isoformat(),
    )["$set"] == {
        "owner": "exec-1",
        "lease_expires_at": expiry,
        "heartbeat_at": "2026-08-17T12:00:00+00:00",
    }


class _HungProcess:
    def __init__(self):
        self.killed = False
        self.communicate_calls = 0

    async def communicate(self):
        self.communicate_calls += 1
        if self.killed:
            return b"", b"killed"
        await asyncio.Event().wait()

    def kill(self):
        self.killed = True


@pytest.mark.asyncio
async def test_process_timeout_kills_and_reaps_child():
    process = _HungProcess()

    with pytest.raises(asyncio.TimeoutError):
        await communicate_process_with_timeout(process, timeout_s=0.01)

    assert process.killed is True
    assert process.communicate_calls == 2


@pytest.mark.asyncio
async def test_outer_cancellation_kills_and_reaps_child():
    """A scene-level wait_for must not leave its ffmpeg child behind."""
    process = _HungProcess()
    task = asyncio.create_task(
        communicate_process_with_timeout(process, timeout_s=60),
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.killed is True
    assert process.communicate_calls == 2
