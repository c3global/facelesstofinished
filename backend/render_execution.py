"""Dependency-free render execution routing decisions."""

from __future__ import annotations


def resolve_execution_backend(configured_backend: str, *, owner_cutover: bool) -> str:
    """Keep the database and Faceless worker cutover atomic."""
    if owner_cutover:
        return "cloud_run_queue"
    return configured_backend.strip().lower() or "local"


def should_use_isolated_queue(*, backend: str, isolated_modes: set[str], mode: str) -> bool:
    return (
        backend.strip().lower() == "cloud_run_queue"
        and mode.strip().lower() in isolated_modes
    )
