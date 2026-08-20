"""Bridge between _run_render_faceless (server.py) and the provider registry.

Keeps the actual scene-motion integration out of the 6.7k-line
server.py while still being invoked from inside the render pipeline.

Two entry points:

  * ``resolve_scene_input_kind(scene)`` — read the frontend/DB
    representation of a scene and return the canonical input_kind
    ("video" | "image" | "stock" | "ai_generated" | "none").
  * ``run_provider_motion(request, ...)`` — submit one SceneMotionRequest
    against the current registry, apply the cost estimator's hard
    ceiling checks, and return a ProviderResult. When the feature flag
    is off OR the registry has no available provider the function
    returns None so the caller (server.py) can fall back to the legacy
    fal.ai path unchanged.

Feature flag:
    USE_PROVIDER_REGISTRY (default "0"). Set to "1" per deployment to
    route AI-motion scenes through the registry.

Server-side circuit breakers are ALWAYS active regardless of flag:
    * RENDER_COST_CAP_CENTS
    * MAX_AI_SCENES_PER_RENDER
Rejections raise ``ProviderPipelineRejected`` which server.py catches
and converts into a customer-safe "over capacity" render failure.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .cost_estimator import (
    estimate_render_cost,
    enforce_render_cost_ceiling,
)
from .registry import get_provider
from .types import (
    MotionInputMode,
    ProviderResult,
    ProviderStatus,
    SceneMotionRequest,
)

logger = logging.getLogger(__name__)


class ProviderPipelineRejected(Exception):
    """Raised when the ceiling / AI-scene limit rejects a render.

    server.py catches this and stamps a customer-safe error on the
    render doc without leaking the cost / provider detail.
    """


def use_registry_enabled() -> bool:
    """True when the deployment has opted into the provider registry."""
    return os.environ.get("USE_PROVIDER_REGISTRY", "0").strip().lower() in ("1", "true", "yes")


def resolve_scene_input_kind(scene: dict[str, Any]) -> str:
    """Read a scene dict (from RenderRequest.scenes[]) and return input_kind.

    Priority:
      1. Explicit ``kind`` field set by MediaLibrary.jsx / Studio.jsx.
      2. Fall back to ``source`` heuristics for legacy payloads.
    """
    kind = (scene.get("kind") or "").strip().lower()
    if kind in {"image", "video"}:
        return kind
    source = (scene.get("source") or "").strip().lower()
    if source == "uploaded":
        # Legacy payload without explicit kind: sniff the URL extension.
        url = (scene.get("video_url") or scene.get("url") or "").lower()
        for ext in (".mp4", ".mov", ".webm", ".mkv"):
            if ext in url:
                return "video"
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            if ext in url:
                return "image"
        return "image"  # safe default — Ken Burns path
    if source == "ai":
        return "ai_generated"
    return "stock"


def enforce_pipeline_ceiling(
    scene_requests: list[tuple[SceneMotionRequest, str]],
    *,
    max_ai_scenes: Optional[int] = None,
    cap_cents: Optional[int] = None,
) -> None:
    """Run cost + AI-scene ceiling checks. Raise if rejected."""
    estimate = estimate_render_cost(
        scene_requests,
        max_ai_scenes=max_ai_scenes,
        cap_cents=cap_cents,
    )
    err = enforce_render_cost_ceiling(estimate)
    if err:
        raise ProviderPipelineRejected(err)


async def run_provider_motion(
    request: SceneMotionRequest,
    *,
    provider_hint: str = "auto",
) -> Optional[ProviderResult]:
    """Run one scene through the registry, or return None to fall back.

    Returns:
      * ``ProviderResult`` (ok=True) on success — caller trims + composes as usual.
      * ``ProviderResult`` (ok=False) on provider failure — caller may
        choose to fall back to fal legacy path.
      * ``None`` when the feature flag is off OR the registry has no
        applicable provider. The caller MUST fall back.
    """
    # Customer-uploaded B-roll and stock footage are assets, not prompts for
    # an AI provider. They always stay on the local normalize/Ken Burns path.
    if request.input_kind in {"image", "video", "stock"}:
        return None
    if not use_registry_enabled():
        return None
    provider = get_provider(provider_hint, request=request)
    if provider is None:
        return None
    try:
        result = await provider.generate(request)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[registry] provider %s raised %s on scene %s",
            getattr(provider, "name", "?"),
            type(exc).__name__,
            request.scene_idx,
        )
        return ProviderResult(
            ok=False,
            provider=getattr(provider, "name", "unknown"),
            model=getattr(provider, "model_id", "unknown"),
            status=ProviderStatus.FAILED,
            error=f"{type(exc).__name__}",
            error_code="pipeline_exception",
        )
    return result


def result_to_scene_telemetry(result: ProviderResult) -> dict[str, Any]:
    """Convert a ProviderResult into the fields we persist on the render doc.

    Written into ``db.renders.scenes[i]`` for admin margin monitoring.
    NEVER exposed to non-admin clients — the response scrub in
    server.py::_scrub_render_for_response strips these fields.
    """
    return {
        "provider": result.provider,
        "model": result.model,
        "external_task_id": result.external_task_id,
        "status": result.status.value,
        "error": result.error,
        "estimated_cost_cents": result.estimated_cost_cents,
        "actual_cost_credits": result.actual_cost_credits,
        "output_url": result.output_url,
        "duration_ms": result.duration_ms,
        "resolution": result.resolution,
    }


__all__ = [
    "ProviderPipelineRejected",
    "enforce_pipeline_ceiling",
    "resolve_scene_input_kind",
    "result_to_scene_telemetry",
    "run_provider_motion",
    "use_registry_enabled",
    "MotionInputMode",
]
