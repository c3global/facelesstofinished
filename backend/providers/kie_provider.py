"""KIE.ai motion provider — model-agnostic.

The KieProvider itself is model-agnostic; concrete model behaviour is
supplied by a ``KieModelSpec`` (see kie_models.py). Deployments enable
specific models via ``KIE_MODELS_ENABLED``; if nothing is enabled the
provider is unavailable and the registry hides it.

Wire contract (unchanged since 2026-08-15):
  * POST https://api.kie.ai/api/v1/jobs/createTask
  * Async: submit → poll ``recordInfo`` → terminal.
  * Callback delivered via HMAC-signed POST — see kie_callback.py.

KIE_API_KEY is read from ``os.environ`` ONLY. Never logged, never
persisted, never echoed in errors.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from .base import VideoMotionProvider
from .kie_models import (
    KieModelSpec,
    default_slug,
    enabled_slugs,
    get_spec,
)
from .types import (
    MotionInputMode,
    ProviderResult,
    ProviderStatus,
    SceneMotionRequest,
)

logger = logging.getLogger(__name__)

KIE_CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

# Poll config
KIE_POLL_INTERVAL_S = float(os.environ.get("KIE_POLL_INTERVAL_S", "4.0"))
KIE_MAX_WAIT_S = float(os.environ.get("KIE_MAX_WAIT_S", "600.0"))

_TERMINAL_SUCCESS = "success"
_TERMINAL_FAIL = "fail"
_TERMINAL_STATES = {_TERMINAL_SUCCESS, _TERMINAL_FAIL}


class KieProvider(VideoMotionProvider):
    """Adapter for KIE.ai video-generation models.

    One instance per (model spec) — the registry constructs and caches
    them lazily as needed.
    """

    name = "kie"

    def __init__(
        self,
        spec: KieModelSpec,
        *,
        api_key: Optional[str] = None,
        callback_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._spec = spec
        self._api_key = api_key if api_key is not None else os.environ.get("KIE_API_KEY", "")
        self._callback_url = callback_url if callback_url is not None else os.environ.get("KIE_CALLBACK_URL", "")
        self._injected_client = http_client
        # Expose the model id for the base class API
        self.model_id = spec.model_id

    @classmethod
    def for_slug(
        cls,
        slug: str,
        *,
        api_key: Optional[str] = None,
        callback_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Optional["KieProvider"]:
        """Construct a provider for a specific model slug, or None if not enabled."""
        spec = get_spec(slug)
        if spec is None:
            return None
        return cls(spec, api_key=api_key, callback_url=callback_url, http_client=http_client)

    # ---- Public interface --------------------------------------------------

    def is_available(self) -> bool:
        return bool(self._api_key) and self._spec.slug in enabled_slugs()

    def supports(self, request: SceneMotionRequest) -> bool:
        return request.mode in self._spec.supported_modes

    def estimate_cost_cents(self, request: SceneMotionRequest) -> int:
        """Compute cost using the spec's per-resolution rate.

        Text-to-video and image-to-video with only image inputs are
        billed at the "no video input" rate. Only requests carrying a
        reference video URL are billed at the (typically lower)
        "with video input" rate.
        """
        duration_s = max(
            self._spec.min_duration_s,
            min(self._spec.max_duration_s, round(request.duration_ms / 1000)),
        )
        resolution = request.resolution if request.resolution in self._spec.allowed_resolutions else next(iter(self._spec.allowed_resolutions))
        pricing = self._spec.pricing.get(resolution)
        if pricing is None:
            # Fall back to the first configured resolution's pricing so we
            # never charge $0 by accident.
            pricing = next(iter(self._spec.pricing.values()))
        if _has_video_input(request):
            rate = pricing.per_sec_with_video_input
        else:
            rate = pricing.per_sec_no_video_input
        # Round UP so the ceiling check never under-charges.
        cents = int(duration_s * rate + 0.999)
        return max(1, cents)

    async def generate(self, request: SceneMotionRequest) -> ProviderResult:
        if not self.is_available():
            return self._fail("kie_provider_unavailable", "KIE not configured or model disabled")

        try:
            payload = self._build_payload(request)
        except ValueError as exc:
            return self._fail("invalid_request", str(exc))

        estimated = self.estimate_cost_cents(request)

        async with self._client() as client:
            try:
                submit = await client.post(
                    KIE_CREATE_URL,
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=30.0,
                )
            except httpx.HTTPError as exc:
                logger.warning("[kie] submit transport error: %s", type(exc).__name__)
                return self._fail("transport_error", type(exc).__name__, estimated_cents=estimated)

            if submit.status_code == 402:
                return self._fail("insufficient_credits", "KIE account has insufficient credits", estimated_cents=estimated)
            if submit.status_code == 429:
                return self._fail("rate_limited", "KIE rate limited", estimated_cents=estimated)
            if submit.status_code >= 400:
                return self._fail(f"http_{submit.status_code}", _safe_error_snippet(submit.text), estimated_cents=estimated)

            body = _safe_json(submit)
            if not body or body.get("code") != 200:
                return self._fail("kie_create_failed", _safe_error_snippet(str(body)), estimated_cents=estimated)
            task_id = ((body.get("data") or {}).get("taskId") or "").strip()
            if not task_id:
                return self._fail("missing_task_id", "KIE createTask returned no taskId", estimated_cents=estimated)

            terminal = await self._poll_to_terminal(client, task_id)

        return self._normalize_terminal(
            terminal,
            task_id=task_id,
            requested_duration_ms=request.duration_ms,
            requested_resolution=request.resolution,
            estimated_cents=estimated,
        )

    # ---- Internals ---------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return _PassthroughClient(self._injected_client)  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0))

    def _fail(self, code: str, message: str, *, task_id: Optional[str] = None, estimated_cents: int = 0) -> ProviderResult:
        return ProviderResult(
            ok=False,
            provider="kie",
            model=self._spec.model_id,
            status=ProviderStatus.FAILED,
            output_url=None,
            external_task_id=task_id,
            estimated_cost_cents=estimated_cents,
            error=message,
            error_code=code,
        )

    def _build_payload(self, req: SceneMotionRequest) -> dict[str, Any]:
        spec = self._spec
        duration_s = round(req.duration_ms / 1000)
        if not (spec.min_duration_s <= duration_s <= spec.max_duration_s):
            raise ValueError(
                f"duration_ms={req.duration_ms} outside {spec.slug} range "
                f"({spec.min_duration_s}-{spec.max_duration_s}s)"
            )
        if req.resolution not in spec.allowed_resolutions:
            raise ValueError(
                f"resolution={req.resolution!r} not in {spec.slug} schema "
                f"({sorted(spec.allowed_resolutions)})."
            )
        if req.aspect_ratio not in spec.allowed_aspects:
            raise ValueError(
                f"aspect_ratio={req.aspect_ratio!r} not in {sorted(spec.allowed_aspects)}"
            )
        if req.mode not in spec.supported_modes:
            raise ValueError(f"{spec.slug} does not support mode={req.mode.value!r}")

        has_first = bool(req.first_frame_url)
        has_last = bool(req.last_frame_url)
        has_refs = bool(req.reference_image_urls)
        has_prompt = bool(req.prompt and req.prompt.strip())

        if req.mode == MotionInputMode.TEXT:
            if not has_prompt:
                raise ValueError("mode=text requires a prompt")
            if has_first or has_last or has_refs:
                raise ValueError("mode=text must not include first/last frame or reference images")
        elif req.mode == MotionInputMode.FIRST_FRAME:
            if not has_first:
                raise ValueError("mode=first_frame requires first_frame_url")
            if has_last:
                raise ValueError("mode=first_frame must not include last_frame_url (use first_and_last_frame)")
            if has_refs:
                raise ValueError("mode=first_frame is mutually exclusive with reference_image_urls")
        elif req.mode == MotionInputMode.FIRST_AND_LAST_FRAME:
            if not (has_first and has_last):
                raise ValueError("mode=first_and_last_frame requires both first_frame_url and last_frame_url")
            if has_refs:
                raise ValueError("first_and_last_frame is mutually exclusive with reference_image_urls")
        elif req.mode == MotionInputMode.MULTIMODAL_REFERENCE:
            if not has_refs:
                raise ValueError("mode=multimodal_reference requires reference_image_urls")
            if has_first or has_last:
                raise ValueError("multimodal_reference is mutually exclusive with first/last-frame mode")

        input_block: dict[str, Any] = {
            "duration": duration_s,
            "resolution": req.resolution,
            "aspect_ratio": req.aspect_ratio,
            "generate_audio": bool(req.generate_audio),
            "output_format": "mp4",
        }
        if has_prompt:
            input_block["prompt"] = req.prompt.strip()  # type: ignore[union-attr]
        if has_first:
            input_block["first_frame_url"] = req.first_frame_url
        if has_last:
            input_block["last_frame_url"] = req.last_frame_url
        if has_refs:
            input_block["reference_image_urls"] = list(req.reference_image_urls)

        payload: dict[str, Any] = {"model": spec.model_id, "input": input_block}
        if self._callback_url:
            payload["callBackUrl"] = self._callback_url
        return payload

    async def _poll_to_terminal(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        deadline = asyncio.get_event_loop().time() + KIE_MAX_WAIT_S
        last_body: dict[str, Any] = {}
        while True:
            try:
                r = await client.get(
                    KIE_RECORD_URL,
                    params={"taskId": task_id},
                    headers=self._auth_headers(),
                    timeout=20.0,
                )
            except httpx.HTTPError as exc:
                logger.warning("[kie] poll transport error: %s", type(exc).__name__)
                if asyncio.get_event_loop().time() >= deadline:
                    return {"code": 0, "data": {"state": "fail", "failMsg": "poll timeout"}}
                await asyncio.sleep(KIE_POLL_INTERVAL_S)
                continue

            body = _safe_json(r) or {}
            last_body = body
            data = body.get("data") or {}
            state = (data.get("state") or "").lower()
            if state in _TERMINAL_STATES:
                return body

            if asyncio.get_event_loop().time() >= deadline:
                last_body.setdefault("data", {})["state"] = "fail"
                last_body["data"]["failMsg"] = "poll timeout"
                return last_body

            await asyncio.sleep(KIE_POLL_INTERVAL_S)

    def _normalize_terminal(
        self,
        terminal: dict[str, Any],
        *,
        task_id: str,
        requested_duration_ms: int,
        requested_resolution: str,
        estimated_cents: int,
    ) -> ProviderResult:
        data = terminal.get("data") or {}
        state = (data.get("state") or "").lower()
        if state == _TERMINAL_SUCCESS:
            result_urls = _extract_result_urls(data)
            if not result_urls:
                return self._fail("empty_result_urls", "KIE reported success but returned no resultUrls", task_id=task_id, estimated_cents=estimated_cents)
            return ProviderResult(
                ok=True,
                provider="kie",
                model=self._spec.model_id,
                status=ProviderStatus.SUCCEEDED,
                output_url=result_urls[0],
                external_task_id=task_id,
                duration_ms=requested_duration_ms,
                resolution=requested_resolution,
                estimated_cost_cents=estimated_cents,
                actual_cost_credits=_safe_float(data.get("creditsConsumed")),
                raw=_safe_raw(data),
            )
        return self._fail(
            data.get("failCode") or "kie_task_failed",
            data.get("failMsg") or "KIE task reached fail state",
            task_id=task_id,
            estimated_cents=estimated_cents,
        )


# ---- Helpers ---------------------------------------------------------------


def _has_video_input(req: SceneMotionRequest) -> bool:
    """True when the request references an input video for billing purposes.

    Seedance 2.5's KIE billing distinguishes "with video input" (any
    reference_video_urls entry) from "no video input" (text, first/last
    image frames, reference images). Uploaded VIDEO scenes are handled
    outside the AI path entirely — see the local_video branch in
    cost_estimator.
    """
    # SceneMotionRequest doesn't currently carry reference_video_urls;
    # reserved for a future model that does. For now, no combination of
    # frontend inputs generates a video-input KIE request.
    return False


def _safe_json(response: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None


def _safe_error_snippet(text: str) -> str:
    return (text or "")[:400]


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_raw(data: dict[str, Any]) -> dict[str, Any]:
    keys = ("state", "resultJson", "costTime", "creditsConsumed", "failCode", "failMsg", "completeTime")
    return {k: data.get(k) for k in keys if k in data}


def _extract_result_urls(data: dict[str, Any]) -> list[str]:
    import json as _json

    rj = data.get("resultJson")
    if not rj:
        return []
    if isinstance(rj, str):
        try:
            rj = _json.loads(rj)
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(rj, dict):
        return []
    urls = rj.get("resultUrls") or rj.get("result_urls") or []
    return [u for u in urls if isinstance(u, str) and u]


class _PassthroughClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


__all__ = ["KieProvider", "KIE_CREATE_URL", "KIE_RECORD_URL"]
