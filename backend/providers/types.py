"""Shared types for the provider abstraction.

Keeps the provider interface transport-agnostic so callers only need to
build a SceneMotionRequest and consume a ProviderResult. The individual
adapters (fal_provider, kie_provider) translate to/from their upstream
wire formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MotionInputMode(str, Enum):
    """Which upstream input mode the caller wants to run.

    KIE's Seedance 2.5 documents these as mutually exclusive; the
    provider adapter enforces the constraint by construction.
    """

    TEXT = "text"
    FIRST_FRAME = "first_frame"
    FIRST_AND_LAST_FRAME = "first_and_last_frame"
    MULTIMODAL_REFERENCE = "multimodal_reference"


class ProviderStatus(str, Enum):
    """Normalized state across all providers.

    fal.ai is effectively synchronous (returns URL in one call).
    KIE.ai is async — the provider wraps polling/callback so callers
    always see one of these terminal states in the returned result.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"  # only surfaced when caller opts out of blocking


@dataclass(frozen=True)
class SceneMotionRequest:
    """Per-scene motion request, provider-agnostic.

    The adapter is responsible for validating combinations against its
    own model constraints (e.g. KIE Seedance rejects
    ``first_and_last_frame`` combined with reference images).
    """

    mode: MotionInputMode
    duration_ms: int
    aspect_ratio: str  # "16:9" | "9:16" | "1:1" | "4:3" | "3:4" | "21:9" | "adaptive"
    resolution: str = "720p"  # provider validates permitted set
    prompt: Optional[str] = None
    first_frame_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    reference_image_urls: tuple[str, ...] = field(default_factory=tuple)
    generate_audio: bool = False  # Studio supplies its own voiceover
    scene_idx: int = 0
    idempotency_key: Optional[str] = None  # optional client-supplied dedupe key
    #: Uploaded asset kind — preserved end-to-end so the render pipeline
    #: can steer video scenes to the free local-normalize path and image
    #: scenes to the customer's chosen motion level.
    input_kind: str = "none"  # "none" | "image" | "video" | "stock" | "ai_generated"


@dataclass
class ProviderResult:
    """Normalized response from any motion provider.

    Persisted per-scene under db.renders.scenes[i] so admin telemetry
    and the future timeline editor can inspect the exact upstream state
    without cross-referencing provider-specific docs.
    """

    ok: bool
    provider: str  # "fal" | "kie"
    model: str  # provider-scoped model id
    status: ProviderStatus
    output_url: Optional[str] = None
    external_task_id: Optional[str] = None
    duration_ms: Optional[int] = None
    resolution: Optional[str] = None
    estimated_cost_cents: int = 0
    actual_cost_credits: Optional[float] = None  # KIE creditsConsumed
    error: Optional[str] = None
    error_code: Optional[str] = None  # provider-scoped code
    raw: Optional[dict] = None  # last provider payload for forensic logging (safe subset)


__all__ = [
    "MotionInputMode",
    "ProviderStatus",
    "SceneMotionRequest",
    "ProviderResult",
]
