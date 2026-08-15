"""Cross-provider cost estimator + hard ceiling enforcement.

Used from two places:
  1. Pre-submission preview endpoint (frontend calls this to display
     the estimated cost before the user clicks "Render").
  2. Server-side render entrypoint (rejects payloads that would
     exceed RENDER_COST_CAP_CENTS OR the per-user MAX_AI_SCENES_PER_RENDER).

The estimator is deliberately conservative — over-estimates are better
than under-charging a customer past their cost cap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional

from .registry import get_provider
from .types import MotionInputMode, SceneMotionRequest


# Global hard ceiling for a single render, in USD cents. Pulled from env
# so ops can adjust without a redeploy. Existing constant lives in
# server.py at 500¢; keep the two in sync.
RENDER_COST_CAP_CENTS = int(os.environ.get("RENDER_COST_CAP_CENTS", "500"))

# Per-render AI scene ceiling. Existing setting in system_config.
# Enforced HERE so the estimator can reject before we submit any paid
# provider request.
MAX_AI_SCENES_PER_RENDER_DEFAULT = int(
    os.environ.get("MAX_AI_SCENES_PER_RENDER", "2")
)

# Local (free) motion cost — Ken Burns is pure ffmpeg on our own box.
LOCAL_KEN_BURNS_CENTS = 0
LOCAL_VIDEO_NORMALIZE_CENTS = 0


@dataclass
class SceneCostBreakdown:
    scene_idx: int
    provider: str  # "kie" | "fal" | "local_ken_burns" | "local_video"
    mode: str
    estimated_cents: int
    notes: Optional[str] = None


@dataclass
class RenderCostEstimate:
    scenes: list[SceneCostBreakdown]
    ai_scene_count: int
    total_cents: int
    cap_cents: int = RENDER_COST_CAP_CENTS
    max_ai_scenes: int = MAX_AI_SCENES_PER_RENDER_DEFAULT
    over_cap: bool = False
    over_ai_limit: bool = False
    provider_selected: Optional[str] = None


def estimate_scene_cost(
    request: SceneMotionRequest,
    *,
    provider_hint: str = "auto",
) -> SceneCostBreakdown:
    """Estimate cost for a single scene.

    ``provider_hint``:
      * "auto" — let the registry pick (KIE preferred).
      * "kie" or "fal" — force the specific provider.
      * "local_ken_burns" — free path for uploaded images that the user
        chose to animate locally instead of via Seedance.
      * "local_video" — free path for uploaded videos (normalize only).
    """
    if provider_hint == "local_ken_burns":
        return SceneCostBreakdown(
            scene_idx=request.scene_idx,
            provider="local_ken_burns",
            mode=request.mode.value,
            estimated_cents=LOCAL_KEN_BURNS_CENTS,
            notes="Free — local ffmpeg Ken Burns motion",
        )
    if provider_hint == "local_video":
        return SceneCostBreakdown(
            scene_idx=request.scene_idx,
            provider="local_video",
            mode=request.mode.value,
            estimated_cents=LOCAL_VIDEO_NORMALIZE_CENTS,
            notes="Free — local ffmpeg trim/normalize on uploaded video",
        )

    provider = get_provider(provider_hint, request=request)
    if provider is None:
        # No provider available/supports this request; treat as free but
        # flagged so the caller can surface the issue.
        return SceneCostBreakdown(
            scene_idx=request.scene_idx,
            provider="unavailable",
            mode=request.mode.value,
            estimated_cents=0,
            notes="No available provider supports this request",
        )

    cents = provider.estimate_cost_cents(request)
    return SceneCostBreakdown(
        scene_idx=request.scene_idx,
        provider=provider.name,
        mode=request.mode.value,
        estimated_cents=cents,
    )


def estimate_render_cost(
    scene_requests: Iterable[tuple[SceneMotionRequest, str]],
    *,
    max_ai_scenes: Optional[int] = None,
    cap_cents: Optional[int] = None,
) -> RenderCostEstimate:
    """Estimate cost + policy compliance for an entire render.

    Args:
        scene_requests: iterable of ``(SceneMotionRequest, provider_hint)``
            tuples — one per scene.
        max_ai_scenes: overrides the env default. Pulled from the
            live system_config in the caller so the current admin
            settings win.
        cap_cents: overrides RENDER_COST_CAP_CENTS. Same intent — let
            the caller inject a per-tier ceiling.
    """
    max_ai = max_ai_scenes if max_ai_scenes is not None else MAX_AI_SCENES_PER_RENDER_DEFAULT
    cap = cap_cents if cap_cents is not None else RENDER_COST_CAP_CENTS

    breakdowns: list[SceneCostBreakdown] = []
    ai_count = 0
    total = 0

    for req, hint in scene_requests:
        b = estimate_scene_cost(req, provider_hint=hint)
        breakdowns.append(b)
        total += b.estimated_cents
        if b.provider in ("kie", "fal"):
            ai_count += 1

    selected_provider: Optional[str] = None
    for b in breakdowns:
        if b.provider in ("kie", "fal"):
            selected_provider = b.provider
            break

    return RenderCostEstimate(
        scenes=breakdowns,
        ai_scene_count=ai_count,
        total_cents=total,
        cap_cents=cap,
        max_ai_scenes=max_ai,
        over_cap=total > cap,
        over_ai_limit=ai_count > max_ai,
        provider_selected=selected_provider,
    )


def enforce_render_cost_ceiling(estimate: RenderCostEstimate) -> Optional[str]:
    """Return an error message if the estimate violates policy, else None.

    Called from the render entrypoint AFTER estimate_render_cost and
    BEFORE any paid provider call fires.
    """
    if estimate.over_cap:
        return (
            f"Estimated cost {estimate.total_cents}¢ exceeds cap {estimate.cap_cents}¢. "
            f"Reduce scene count or switch AI scenes to Ken Burns."
        )
    if estimate.over_ai_limit:
        return (
            f"This render includes {estimate.ai_scene_count} AI scenes but the current "
            f"limit is {estimate.max_ai_scenes} per render."
        )
    return None


__all__ = [
    "MotionInputMode",  # re-export for convenience
    "RenderCostEstimate",
    "SceneCostBreakdown",
    "estimate_scene_cost",
    "estimate_render_cost",
    "enforce_render_cost_ceiling",
    "RENDER_COST_CAP_CENTS",
    "MAX_AI_SCENES_PER_RENDER_DEFAULT",
]
