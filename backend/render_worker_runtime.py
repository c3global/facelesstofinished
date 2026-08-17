"""Dependency-free helpers for the isolated render worker."""
from __future__ import annotations

from datetime import datetime, timezone


TERMINAL_RENDER_STATUSES = frozenset({"complete", "failed"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker_claim_query(job_id: str) -> dict:
    """Atomically claim only a never-started render."""
    return {
        "id": job_id,
        "status": "queued",
        "$or": [
            {"worker_execution_id": {"$exists": False}},
            {"worker_execution_id": None},
        ],
    }


def worker_claim_update(execution_id: str, *, now_iso: str | None = None) -> dict:
    now = now_iso or utc_now_iso()
    return {
        "$set": {
            "worker_backend": "cloud_run_job",
            "worker_execution_id": execution_id,
            "worker_claimed_at": now,
            "updated_at": now,
            "progress_label": "Render worker starting…",
        }
    }


def worker_interrupted_update(execution_id: str, *, now_iso: str | None = None) -> dict:
    now = now_iso or utc_now_iso()
    return {
        "$set": {
            "status": "failed",
            "error": "The isolated render worker stopped before completion.",
            "progress_label": "Render worker interrupted",
            "worker_interrupted": True,
            "worker_execution_id": execution_id,
            "updated_at": now,
            "completed_at": now,
        }
    }


def terminal_exit_code(status: str | None) -> int:
    return 0 if status == "complete" else 1
