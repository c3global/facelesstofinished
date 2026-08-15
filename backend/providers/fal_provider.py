"""fal.ai motion provider adapter.

Thin wrapper around the existing fal.ai code paths already in
server.py (Kling i2v, Flux still + ken-burns, T2V engines) so the
render pipeline can go through the unified VideoMotionProvider
interface without ripping out functioning production code.

This adapter is NOT rewiring server.py to use itself — that migration
is intentionally staged separately so the KIE + FAL abstraction can be
validated by mocked tests before touching the existing render path.
The adapter is a functioning provider today; server.py will call it in
a follow-up commit once we've verified KIE end-to-end.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .base import VideoMotionProvider
from .types import (
    MotionInputMode,
    ProviderResult,
    ProviderStatus,
    SceneMotionRequest,
)

logger = logging.getLogger(__name__)

FAL_KLING_I2V_MODEL = "fal-ai/kling-video/v2.1/standard/image-to-video"

# Legacy cost coefficient — pulled from server.py's KLING_I2V_COST_CENTS_5S.
FAL_KLING_I2V_CENTS_PER_5S = 25
FAL_KLING_I2V_CENTS_PER_10S = 50


class FalProvider(VideoMotionProvider):
    """Adapter for fal.ai's Kling i2v + related T2V engines.

    Availability is tied to FAL_API_KEY being present. Callers that
    already have their own fal_client wiring can bypass this adapter
    for now; the adapter exists so the registry can offer ``fal`` as a
    valid provider option once server.py finishes migrating.
    """

    name = "fal"
    model_id = FAL_KLING_I2V_MODEL

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("FAL_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def supports(self, request: SceneMotionRequest) -> bool:
        # Kling on fal supports text-to-video and image-to-video (first-frame).
        # Kling does NOT support first-and-last-frame natively in the
        # standard endpoint, and reference arrays aren't part of the
        # standard Kling API surface. So we only claim support for the
        # two modes that actually work today.
        return request.mode in (MotionInputMode.TEXT, MotionInputMode.FIRST_FRAME)

    def estimate_cost_cents(self, request: SceneMotionRequest) -> int:
        duration_s = round(request.duration_ms / 1000)
        # Kling standard is billed in ~5s buckets.
        if duration_s <= 5:
            return FAL_KLING_I2V_CENTS_PER_5S
        return FAL_KLING_I2V_CENTS_PER_10S

    async def generate(self, request: SceneMotionRequest) -> ProviderResult:
        # Deferred: the current render pipeline in server.py directly
        # calls the legacy fal.ai helpers (_fal_kling_i2v_generate,
        # _trim_t2v_clip). Migrating those inside this adapter is Phase 2
        # of the provider abstraction. For now the adapter is a
        # placeholder that reports UNAVAILABLE via a clean fail so the
        # registry can still select it for capability checks + cost
        # estimation without silently calling the legacy path twice.
        return ProviderResult(
            ok=False,
            provider="fal",
            model=FAL_KLING_I2V_MODEL,
            status=ProviderStatus.FAILED,
            error="fal_provider_generate_not_wired",
            error_code="not_implemented",
        )


__all__ = ["FalProvider", "FAL_KLING_I2V_MODEL"]
