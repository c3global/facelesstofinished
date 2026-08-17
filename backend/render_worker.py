"""Cloud Run Job entry point for the serialized Faceless48 render queue.

This process exposes no HTTP port. Scheduled executions select the oldest
queued Faceless render; a job ID can still be supplied for controlled staging.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import uuid
from datetime import datetime, timezone

from render_worker_runtime import (
    TERMINAL_RENDER_STATUSES,
    terminal_exit_code,
    worker_claim_query,
    worker_claim_update,
    worker_interrupted_update,
)
from render_runtime import (
    RENDER_QUEUE_LOCK_ID,
    lease_expiry_iso,
    queued_render_query,
    worker_lock_query,
    worker_lock_update,
)

logger = logging.getLogger("f48.render_worker")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Faceless48 render job")
    parser.add_argument("--job-id", default=os.environ.get("RENDER_JOB_ID"))
    parser.add_argument("--execution-id", default=os.environ.get("RENDER_EXECUTION_ID"))
    args = parser.parse_args()
    if not args.execution_id:
        args.execution_id = os.environ.get("CLOUD_RUN_EXECUTION") or uuid.uuid4().hex
    return args


async def _acquire_queue_lock(db, execution_id: str, lease_s: int) -> bool:
    from pymongo.errors import DuplicateKeyError  # noqa: PLC0415

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        result = await db.render_worker_locks.update_one(
            worker_lock_query(execution_id, now_iso=now_iso),
            worker_lock_update(
                execution_id,
                lease_expires_at=lease_expiry_iso(seconds=lease_s),
                now_iso=now_iso,
            ),
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    return bool(result.modified_count or result.upserted_id)


async def _maintain_queue_lock(
    db,
    execution_id: str,
    *,
    lease_s: int,
    interval_s: int,
    stop_requested: asyncio.Event,
) -> None:
    while not stop_requested.is_set():
        try:
            await asyncio.wait_for(stop_requested.wait(), timeout=interval_s)
            return
        except asyncio.TimeoutError:
            pass
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            result = await db.render_worker_locks.update_one(
                {"_id": RENDER_QUEUE_LOCK_ID, "owner": execution_id},
                worker_lock_update(
                    execution_id,
                    lease_expires_at=lease_expiry_iso(seconds=lease_s),
                    now_iso=now_iso,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — fail closed on lease uncertainty
            logger.error(
                "render queue lease heartbeat failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            stop_requested.set()
            return
        if result.matched_count != 1:
            logger.error("render queue lease was lost: execution=%s", execution_id)
            stop_requested.set()
            return


async def _release_queue_lock(db, execution_id: str) -> None:
    await db.render_worker_locks.delete_one(
        {"_id": RENDER_QUEUE_LOCK_ID, "owner": execution_id},
    )


async def _run(requested_job_id: str | None, execution_id: str) -> int:
    # Delayed import lets --help work without production environment secrets.
    from server import (  # noqa: PLC0415
        _cleanup_job_workdir,
        _refund_render_quota_once,
        _run_render,
        db,
        mongo,
    )

    lease_s = max(60, int(os.environ.get("RENDER_WORKER_LOCK_LEASE_S", "180")))
    lock_interval_s = max(10, int(os.environ.get("RENDER_WORKER_LOCK_HEARTBEAT_S", "30")))
    if not await _acquire_queue_lock(db, execution_id, lease_s):
        logger.info("another render worker owns the queue lease; exiting")
        mongo.close()
        return 0

    job_id = requested_job_id
    if not job_id:
        queued = await db.renders.find_one(
            queued_render_query(),
            {"id": 1},
            sort=[("created_at", 1)],
        )
        if not queued:
            logger.info("render queue is empty")
            try:
                await _release_queue_lock(db, execution_id)
            finally:
                mongo.close()
            return 0
        job_id = queued["id"]

    claim = await db.renders.update_one(
        worker_claim_query(job_id), worker_claim_update(execution_id),
    )
    if claim.modified_count != 1:
        existing = await db.renders.find_one(
            {"id": job_id}, {"status": 1, "worker_execution_id": 1},
        )
        try:
            await _release_queue_lock(db, execution_id)
        finally:
            mongo.close()
        if existing and existing.get("status") == "complete":
            logger.info("render job %s is already complete; no-op", job_id)
            return 0
        logger.error(
            "render job %s was not claimed (status=%s worker=%s)",
            job_id,
            (existing or {}).get("status"),
            (existing or {}).get("worker_execution_id"),
        )
        return 2

    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_requested.set)
        except (NotImplementedError, RuntimeError):
            pass

    lock_task = asyncio.create_task(
        _maintain_queue_lock(
            db,
            execution_id,
            lease_s=lease_s,
            interval_s=lock_interval_s,
            stop_requested=stop_requested,
        ),
    )

    render_task = asyncio.create_task(_run_render(job_id))
    stop_task = asyncio.create_task(stop_requested.wait())
    try:
        done, _ = await asyncio.wait(
            {render_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done and stop_requested.is_set() and not render_task.done():
            logger.warning("render worker interrupted: job=%s", job_id)
            render_task.cancel()
            try:
                await render_task
            except asyncio.CancelledError:
                pass
            current = await db.renders.find_one({"id": job_id}, {"status": 1})
            if current and current.get("status") not in TERMINAL_RENDER_STATUSES:
                await db.renders.update_one(
                    {"id": job_id, "status": {"$nin": list(TERMINAL_RENDER_STATUSES)}},
                    worker_interrupted_update(execution_id),
                )
                refund_doc = await db.renders.find_one(
                    {"id": job_id},
                    {"user_email": 1, "mode": 1, "estimated_cost_cents": 1},
                )
                if refund_doc:
                    refund_doc["id"] = job_id
                    await _refund_render_quota_once(refund_doc)
            _cleanup_job_workdir(job_id)
            return 143

        stop_task.cancel()
        try:
            await stop_task
        except asyncio.CancelledError:
            pass
        await render_task
        final = await db.renders.find_one({"id": job_id}, {"status": 1})
        return terminal_exit_code((final or {}).get("status"))
    finally:
        stop_requested.set()
        if not lock_task.done():
            lock_task.cancel()
        try:
            await lock_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 — cleanup must still release the lease
            logger.error("render queue lease task failed: %s: %s", type(exc).__name__, exc)
        try:
            await _release_queue_lock(db, execution_id)
        finally:
            mongo.close()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _arguments()
    return asyncio.run(_run(args.job_id, args.execution_id))


if __name__ == "__main__":
    raise SystemExit(main())
