"""Cloud Run Job entry point for one Faceless48 render.

This process exposes no HTTP port. The existing Emergent API must not dispatch
here until its local ``asyncio.create_task`` handoff has been replaced.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import uuid

from render_worker_runtime import (
    TERMINAL_RENDER_STATUSES,
    terminal_exit_code,
    worker_claim_query,
    worker_claim_update,
    worker_interrupted_update,
)

logger = logging.getLogger("f48.render_worker")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Faceless48 render job")
    parser.add_argument("--job-id", default=os.environ.get("RENDER_JOB_ID"))
    parser.add_argument("--execution-id", default=os.environ.get("RENDER_EXECUTION_ID"))
    args = parser.parse_args()
    if not args.job_id:
        parser.error("--job-id or RENDER_JOB_ID is required")
    if not args.execution_id:
        args.execution_id = uuid.uuid4().hex
    return args


async def _run(job_id: str, execution_id: str) -> int:
    # Delayed import lets --help work without production environment secrets.
    from server import (  # noqa: PLC0415
        _cleanup_job_workdir,
        _refund_render_quota_once,
        _run_render,
        db,
        mongo,
    )

    claim = await db.renders.update_one(
        worker_claim_query(job_id),
        worker_claim_update(execution_id),
    )
    if claim.modified_count != 1:
        existing = await db.renders.find_one(
            {"id": job_id}, {"status": 1, "worker_execution_id": 1},
        )
        if not existing:
            logger.error("render job %s does not exist", job_id)
            mongo.close()
            return 2
        if existing.get("status") == "complete":
            logger.info("render job %s is already complete; no-op", job_id)
            mongo.close()
            return 0
        logger.error(
            "render job %s was not claimed (status=%s worker=%s)",
            job_id, existing.get("status"), existing.get("worker_execution_id"),
        )
        mongo.close()
        return 2

    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_requested.set)
        except (NotImplementedError, RuntimeError):
            pass

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
