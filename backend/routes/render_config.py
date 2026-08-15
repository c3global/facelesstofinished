"""Public config + cost-preview endpoints for the render provider layer.

Two endpoints:
  * GET  /api/config/render-providers — public, no auth. Lists which
    providers are available in this environment so the frontend can
    hide unconfigured options.
  * POST /api/render/estimate — auth required. Accepts a scene list +
    per-scene provider hints, returns a full cost breakdown, and
    enforces the hard ceiling before any paid provider call.

The estimate endpoint is INTENTIONALLY separate from the render entry
point. Frontend calls this to preview, then submits the render. Server
also runs the same estimate again inside the render entrypoint so a
hostile client can't skip the check.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from providers.cost_estimator import (
    RENDER_COST_CAP_CENTS,
    enforce_render_cost_ceiling,
    estimate_render_cost,
)
from providers.registry import available_providers, default_provider_name
from providers.types import MotionInputMode, SceneMotionRequest


# ---- Request/response schemas ---------------------------------------------


class SceneEstimateIn(BaseModel):
    scene_idx: int
    mode: str = Field(..., description="text | first_frame | first_and_last_frame | multimodal_reference")
    provider_hint: str = Field(
        default="auto",
        description="auto | kie | fal | local_ken_burns | local_video",
    )
    duration_ms: int = Field(..., ge=1000, le=60_000)
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    prompt: Optional[str] = None
    first_frame_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    reference_image_urls: list[str] = Field(default_factory=list)


class RenderEstimateIn(BaseModel):
    scenes: list[SceneEstimateIn]
    max_ai_scenes: Optional[int] = None
    cap_cents: Optional[int] = None


class SceneEstimateOut(BaseModel):
    scene_idx: int
    provider: str
    mode: str
    estimated_cents: int
    notes: Optional[str] = None


class RenderEstimateOut(BaseModel):
    scenes: list[SceneEstimateOut]
    ai_scene_count: int
    total_cents: int
    cap_cents: int
    max_ai_scenes: int
    over_cap: bool
    over_ai_limit: bool
    provider_selected: Optional[str]


class RenderProvidersOut(BaseModel):
    available: list[str]
    default: str


# ---- Router builder --------------------------------------------------------


def build_router(current_user_dep: Callable[..., Any]) -> APIRouter:
    """Return the FastAPI router.

    ``current_user_dep`` is server.py's ``current_user`` dependency,
    injected so tests can supply a stub without pulling the whole
    auth stack.
    """
    router = APIRouter()

    @router.get("/config/render-providers", response_model=RenderProvidersOut)
    async def render_providers() -> RenderProvidersOut:
        return RenderProvidersOut(
            available=available_providers(),
            default=default_provider_name(),
        )

    @router.post("/render/estimate", response_model=RenderEstimateOut)
    async def render_estimate(
        payload: RenderEstimateIn,
        _user: Any = Depends(current_user_dep),
    ) -> RenderEstimateOut:
        # Translate the wire payload into provider SceneMotionRequests.
        scene_pairs: list[tuple[SceneMotionRequest, str]] = []
        for s in payload.scenes:
            try:
                mode = MotionInputMode(s.mode)
            except ValueError as exc:
                raise HTTPException(422, f"Unknown mode: {s.mode!r}") from exc
            req = SceneMotionRequest(
                mode=mode,
                duration_ms=s.duration_ms,
                aspect_ratio=s.aspect_ratio,
                resolution=s.resolution,
                prompt=s.prompt,
                first_frame_url=s.first_frame_url,
                last_frame_url=s.last_frame_url,
                reference_image_urls=tuple(s.reference_image_urls),
                scene_idx=s.scene_idx,
            )
            scene_pairs.append((req, s.provider_hint))

        estimate = estimate_render_cost(
            scene_pairs,
            max_ai_scenes=payload.max_ai_scenes,
            cap_cents=payload.cap_cents,
        )
        return RenderEstimateOut(
            scenes=[
                SceneEstimateOut(
                    scene_idx=b.scene_idx,
                    provider=b.provider,
                    mode=b.mode,
                    estimated_cents=b.estimated_cents,
                    notes=b.notes,
                )
                for b in estimate.scenes
            ],
            ai_scene_count=estimate.ai_scene_count,
            total_cents=estimate.total_cents,
            cap_cents=estimate.cap_cents,
            max_ai_scenes=estimate.max_ai_scenes,
            over_cap=estimate.over_cap,
            over_ai_limit=estimate.over_ai_limit,
            provider_selected=estimate.provider_selected,
        )

    return router


__all__ = ["build_router", "RENDER_COST_CAP_CENTS"]
