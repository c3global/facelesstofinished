"""Provider abstraction for AI video generation.

Introduced on feature/kie-dual-provider so the render engine can select
between fal.ai (legacy default) and KIE.ai (new primary) without
duplicating the entire pipeline. Local ffmpeg composition / captions /
Kokoro TTS all remain outside this module — they're not "providers" in
the swappable sense.

Entry points:
    from providers.registry import get_provider, available_providers
    from providers.types import ProviderResult, SceneMotionRequest
"""

from .types import (
    ProviderResult,
    SceneMotionRequest,
    ProviderStatus,
    MotionInputMode,
)
from .registry import (
    get_provider,
    available_providers,
    default_provider_name,
)

__all__ = [
    "ProviderResult",
    "SceneMotionRequest",
    "ProviderStatus",
    "MotionInputMode",
    "get_provider",
    "available_providers",
    "default_provider_name",
]
