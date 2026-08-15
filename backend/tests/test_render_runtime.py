import asyncio

import pytest

from render_runtime import communicate_process_with_timeout, stale_render_query


def test_stale_query_covers_visuals_and_future_nonterminal_statuses():
    query = stale_render_query("2026-08-14T11:55:00+00:00")

    # Regression: v1.20.9 used status="visuals" at 55-69%, but the reaper's
    # old allowlist omitted it. A terminal denylist covers it automatically.
    assert query["status"] == {"$nin": ["complete", "failed"]}
    assert query["$or"][0] == {
        "updated_at": {"$lt": "2026-08-14T11:55:00+00:00"},
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
