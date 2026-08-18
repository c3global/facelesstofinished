"""Public config + cost-preview endpoints for the render provider layer.

CUSTOMER-FACING PRIVACY RULE (locked 2026-08-15 by product):
  * Non-admin responses MUST NOT expose:
      - provider names (kie / fal)
      - model IDs (bytedance/seedance-2-5, fal-ai/kling-video/...)
      - dollar / cent estimates
      - internal spending limits (cap_cents, RENDER_COST_CAP_CENTS)
      - per-scene cost breakdowns
  * Non-admin responses MAY include:
      - opaque quality label (standard / premium)
      - estimated completion time in seconds
      - scene count + AI vs local scene counts (no cost attached)
      - a plain-language over_capacity boolean (no cap value revealed)
  * Admin responses (is_admin=True) include the full breakdown for
    circuit-breaker tuning + margin monitoring.

Endpoints:
  * GET  /api/config/render-providers — public, no auth.
        NON-ADMIN body: {"has_premium_motion": bool}.
        Provider names never appear in this endpoint's response.
  * POST /api/render/estimate — auth-gated.
        Non-admin body: quality label + completion estimate + over_capacity flag.
        Admin body: full cost breakdown (opt-in via ?detail=admin).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from providers.cost_estimator import (
    RENDER_COST_CAP_CENTS,
    RenderCostEstimate,
    SceneCostBreakdown,
    enforce_render_cost_ceiling,
    estimate_render_cost,
)
from providers.registry import available_providers, default_provider_name
from providers.types import MotionInputMode, SceneMotionRequest


# ---- Request schema (customer input — no cost/provider leakage) -----------


class SceneEstimateIn(BaseModel):
    scene_idx: int
    mode: str = Field(..., description="text | first_frame | first_and_last_frame | multimodal_reference")
    # ``motion_quality`` replaces the previous provider_hint so the wire
    # payload from the browser NEVER carries a provider name. The server
    # translates quality → concrete provider using the current admin
    # config.
    motion_quality: str = Field(
        default="auto",
        description="auto | premium (AI motion) | standard (local Ken Burns / video normalize)",
    )
    duration_ms: int = Field(..., ge=1000, le=60_000)
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    prompt: Optional[str] = None
    first_frame_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    reference_image_urls: list[str] = Field(default_factory=list)
    #: True when the scene's source asset is an uploaded video (not an
    #: image). Videos take the free local-normalize path regardless of
    #: motion_quality.
    input_is_video: bool = False


class RenderEstimateIn(BaseModel):
    scenes: list[SceneEstimateIn]
    #: Admin only — non-admin callers cannot override the cap
    max_ai_scenes: Optional[int] = None
    cap_cents: Optional[int] = None


# ---- Customer-facing response schemas -------------------------------------


class CustomerSceneOut(BaseModel):
    scene_idx: int
    mode: str
    quality_level: str  # "standard" | "premium"
    #: True iff this scene will run against a paid AI provider. NO cost
    #: field, NO provider name.
    is_ai_motion: bool


class CustomerRenderEstimateOut(BaseModel):
    scenes: list[CustomerSceneOut]
    ai_scene_count: int
    total_scene_count: int
    estimated_completion_seconds: int
    over_capacity: bool
    over_capacity_reason: Optional[str] = None


class CustomerProvidersOut(BaseModel):
    """Public capability disclosure. No provider names, ever."""

    has_premium_motion: bool


# ---- Admin-only response schemas (full detail) ----------------------------


class AdminSceneOut(BaseModel):
    scene_idx: int
    provider: str
    mode: str
    estimated_cents: int
    notes: Optional[str] = None


class AdminRenderEstimateOut(BaseModel):
    scenes: list[AdminSceneOut]
    ai_scene_count: int
    total_cents: int
    cap_cents: int
    max_ai_scenes: int
    over_cap: bool
    over_ai_limit: bool
    provider_selected: Optional[str]
    estimated_completion_seconds: int


class AdminProvidersOut(BaseModel):
    available: list[str]
    default: str


# ---- Helpers --------------------------------------------------------------


# Quality label ↔ provider hint translation. Kept as functions rather than a
# static dict so tests can monkeypatch the mapping if we add a "cinematic"
# tier later.
_AI_PROVIDER_HINTS = {"auto", "kie", "fal"}
_LOCAL_PROVIDER_HINTS = {"local_ken_burns", "local_video"}


def _resolve_hint(scene: SceneEstimateIn) -> str:
    """Translate customer-facing quality label + input type → provider hint."""
    if scene.input_is_video:
        return "local_video"
    q = (scene.motion_quality or "auto").strip().lower()
    if q == "standard":
        return "local_ken_burns"
    if q == "premium":
        return "auto"  # let registry pick the best available AI provider
    # "auto" default: AI if available, no explicit downgrade
    return "auto"


def _scene_quality_label(breakdown: SceneCostBreakdown) -> str:
    if breakdown.provider in {"kie", "fal"}:
        return "premium"
    return "standard"


def _is_ai_scene(breakdown: SceneCostBreakdown) -> bool:
    return breakdown.provider in {"kie", "fal"}


def _estimate_completion_seconds(estimate: RenderCostEstimate) -> int:
    """Rough completion-time estimator surfaced to customers.

    Baseline overhead (~30s) covers Kokoro TTS start + compose + upload.
    Per-scene contribution is 3s for local scenes and 12s for AI scenes
    (Seedance polling amortized). This is deliberately a customer-safe
    approximation — admin telemetry uses actual timing from the render
    row instead.
    """
    n_total = len(estimate.scenes)
    n_ai = estimate.ai_scene_count
    n_local = max(0, n_total - n_ai)
    return int(30 + (n_local * 3) + (n_ai * 12))


def _customer_over_capacity_reason(estimate: RenderCostEstimate) -> Optional[str]:
    """Return a customer-safe explanation of over-capacity, without
    revealing cost caps or provider names."""
    if estimate.over_ai_limit:
        return (
            f"This render uses more premium-motion scenes than your current plan allows "
            f"({estimate.max_ai_scenes} max). Reduce premium scenes or switch some to Standard motion."
        )
    if estimate.over_cap:
        return "This render exceeds the current per-render capacity. Reduce scene count or lower motion quality."
    return None


def _scene_pairs_from_payload(payload: RenderEstimateIn) -> list[tuple[SceneMotionRequest, str]]:
    pairs: list[tuple[SceneMotionRequest, str]] = []
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
            input_kind="video" if s.input_is_video else "image",
        )
        pairs.append((req, _resolve_hint(s)))
    return pairs


def _customer_view(estimate: RenderCostEstimate) -> CustomerRenderEstimateOut:
    return CustomerRenderEstimateOut(
        scenes=[
            CustomerSceneOut(
                scene_idx=b.scene_idx,
                mode=b.mode,
                quality_level=_scene_quality_label(b),
                is_ai_motion=_is_ai_scene(b),
            )
            for b in estimate.scenes
        ],
        ai_scene_count=estimate.ai_scene_count,
        total_scene_count=len(estimate.scenes),
        estimated_completion_seconds=_estimate_completion_seconds(estimate),
        over_capacity=estimate.over_cap or estimate.over_ai_limit,
        over_capacity_reason=_customer_over_capacity_reason(estimate),
    )


def _admin_view(estimate: RenderCostEstimate) -> AdminRenderEstimateOut:
    return AdminRenderEstimateOut(
        scenes=[
            AdminSceneOut(
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
        estimated_completion_seconds=_estimate_completion_seconds(estimate),
    )


# ---- Router builder --------------------------------------------------------


def build_router(current_user_dep: Callable[..., Any]) -> APIRouter:
    """Return the FastAPI router.

    ``current_user_dep`` is server.py's ``current_user`` dependency,
    injected so tests can supply a stub without pulling the whole
    auth stack.
    """
    router = APIRouter()

    @router.get("/config/render-providers", response_model=CustomerProvidersOut)
    async def render_providers_public() -> CustomerProvidersOut:
        """Public capability disclosure. Provider names NEVER surface here."""
        names = available_providers()
        has_ai = any(n in {"kie", "fal"} for n in names)
        return CustomerProvidersOut(has_premium_motion=has_ai)

    @router.get("/admin/render/providers", response_model=AdminProvidersOut)
    async def render_providers_admin(user: Any = Depends(current_user_dep)) -> AdminProvidersOut:
        if not getattr(user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin only")
        return AdminProvidersOut(
            available=available_providers(),
            default=default_provider_name(),
        )

    @router.post("/render/estimate", response_model=CustomerRenderEstimateOut)
    async def render_estimate(
        payload: RenderEstimateIn,
        _user: Any = Depends(current_user_dep),
    ) -> CustomerRenderEstimateOut:
        """Customer-facing estimate — no dollars, no providers, no models."""
        # Ignore non-admin cap overrides (privacy + prevent manipulation).
        pairs = _scene_pairs_from_payload(payload)
        estimate = estimate_render_cost(pairs)
        return _customer_view(estimate)

    @router.post("/admin/render/estimate", response_model=AdminRenderEstimateOut)
    async def render_estimate_admin(
        payload: RenderEstimateIn,
        user: Any = Depends(current_user_dep),
    ) -> AdminRenderEstimateOut:
        if not getattr(user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin only")
        pairs = _scene_pairs_from_payload(payload)
        estimate = estimate_render_cost(
            pairs,
            max_ai_scenes=payload.max_ai_scenes,
            cap_cents=payload.cap_cents,
        )
        return _admin_view(estimate)

    return router


__all__ = ["build_router", "RENDER_COST_CAP_CENTS"]
