"""Customer-facing projection for render documents."""

from __future__ import annotations

from typing import Any


_PRIVATE_FIELDS = {
    "actual_cost_cents",
    "ai_engine",
    "cap_cents",
    "estimated_cost_cents",
    "estimated_cost_dollars",
    "fal_request_id",
    "kie_task_id",
    "local_compose_debug",
    "model",
    "provider",
    "quota_refunded_at",
    "reaped_by_watchdog",
    "user_entitlements",
    "user_is_admin",
    "_provider_telemetry",
}


def scrub_render_for_customer(value: Any) -> Any:
    """Recursively remove internal cost/provider data from response JSON."""

    if isinstance(value, dict):
        return {
            key: scrub_render_for_customer(item)
            for key, item in value.items()
            if key not in _PRIVATE_FIELDS and not key.startswith("_provider_")
        }
    if isinstance(value, list):
        return [scrub_render_for_customer(item) for item in value]
    return value
