"""Dependency-free render execution routing decisions."""

from __future__ import annotations


def should_use_isolated_queue(*, backend: str, isolated_modes: set[str], mode: str) -> bool:
    return (
        backend.strip().lower() == "cloud_run_queue"
        and mode.strip().lower() in isolated_modes
    )
