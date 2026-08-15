"""KIE.ai Seedance 2.5 motion provider.

Wire contract confirmed 2026-08-15:
  * POST https://api.kie.ai/api/v1/jobs/createTask
      body: {"model": "bytedance/seedance-2-5",
             "callBackUrl": "<PUBLIC_API_URL>/api/kie/webhook",
             "input": {...}}
  * Async: POST returns {"code":200,"data":{"taskId":"..."}} only.
  * Poll  GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=<id>
      state ∈ {waiting, queuing, generating, success, fail}.
  * Callback delivered via HMAC-signed POST — see kie_callback.py.

Field constraints (Seedance 2.5 API schema, not marketing copy):
  * Resolution: "480p" or "720p" ONLY. 1080p/4K are marketing.
  * Duration: integer 4-30 seconds. Default 5.
  * Aspect ratio: 1:1, 4:3, 3:4, 16:9, 9:16, 21:9, adaptive.
  * first_frame_url (NOT image_url) for image → video.
  * last_frame_url (NOT end_image_url) — requires first_frame_url.
  * reference_image_urls (array, JPEG/PNG/WebP/GIF, ≤30MB each).
  * first/last-frame mode ⊥ reference arrays (mutually exclusive).
  * generate_audio: bool (Studio always sends False; we supply Kokoro).

KIE_API_KEY is read from os.environ ONLY. Never logged, never persisted,
never echoed in errors. If the env var is missing the provider reports
``is_available() == False`` and the registry hides it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from .base import VideoMotionProvider
from .types import (
    MotionInputMode,
    ProviderResult,
    ProviderStatus,
    SceneMotionRequest,
)

logger = logging.getLogger(__name__)

# ---- Wire endpoints (public, no secret) ------------------------------------
KIE_CREATE_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_MODEL_ID = "bytedance/seedance-2-5"

# ---- Schema-permitted values (validated by construction) -------------------
_ALLOWED_RESOLUTIONS = frozenset({"480p", "720p"})
_ALLOWED_ASPECTS = frozenset(
    {"1:1", "4:3", "3:4", "16:9", "9:16", "21:9", "adaptive"}
)
_MIN_DURATION_S = 4
_MAX_DURATION_S = 30

# ---- Poll config (env-overridable, safe defaults) --------------------------
KIE_POLL_INTERVAL_S = float(os.environ.get("KIE_POLL_INTERVAL_S", "4.0"))
KIE_MAX_WAIT_S = float(os.environ.get("KIE_MAX_WAIT_S", "600.0"))  # 10 min ceiling

# ---- Cost estimator config (env-overridable) -------------------------------
# KIE does NOT publish a Seedance 2.5 rate card in their public docs. These
# values are pre-render ESTIMATES only, used to display a cost preview and
# enforce a hard ceiling. Post-completion we record the real ``creditsConsumed``
# from KIE's task record. Update via env if KIE publishes a rate card.
KIE_PRICE_CENTS_480P_PER_SEC = float(os.environ.get("KIE_PRICE_CENTS_480P_PER_SEC", "1.5"))
KIE_PRICE_CENTS_720P_PER_SEC = float(os.environ.get("KIE_PRICE_CENTS_720P_PER_SEC", "3.0"))

# ---- Terminal states from KIE ---------------------------------------------
_TERMINAL_SUCCESS = "success"
_TERMINAL_FAIL = "fail"
_TERMINAL_STATES = {_TERMINAL_SUCCESS, _TERMINAL_FAIL}


class KieProvider(VideoMotionProvider):
    """Adapter for KIE.ai Seedance 2.5.

    Concurrency-safe: one instance per process is fine, all state lives
    on the request object.
    """

    name = "kie"
    model_id = KIE_MODEL_ID

    def __init__(
        self,
        api_key: Optional[str] = None,
        callback_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        # Read from environment on construction; do NOT re-read per call
        # to keep test injection deterministic.
        self._api_key = api_key if api_key is not None else os.environ.get("KIE_API_KEY", "")
        self._callback_url = callback_url if callback_url is not None else os.environ.get(
            "KIE_CALLBACK_URL", ""
        )
        # http_client injectable for mocked tests. When None we build a
        # short-lived client per request so we don't leak sockets in the
        # server's global-instance lifetime.
        self._injected_client = http_client

    # ---- Public interface -------------------------------------------------

    def is_available(self) -> bool:
        return bool(self._api_key)

    def supports(self, request: SceneMotionRequest) -> bool:
        # Seedance 2.5 covers all 4 input modes.
        return request.mode in (
            MotionInputMode.TEXT,
            MotionInputMode.FIRST_FRAME,
            MotionInputMode.FIRST_AND_LAST_FRAME,
            MotionInputMode.MULTIMODAL_REFERENCE,
        )

    def estimate_cost_cents(self, request: SceneMotionRequest) -> int:
        duration_s = max(_MIN_DURATION_S, min(_MAX_DURATION_S, round(request.duration_ms / 1000)))
        if request.resolution == "480p":
            rate = KIE_PRICE_CENTS_480P_PER_SEC
        else:
            rate = KIE_PRICE_CENTS_720P_PER_SEC
        # Round UP so the ceiling check never under-charges by a fraction.
        cents = int(duration_s * rate + 0.999)
        return max(1, cents)

    async def generate(self, request: SceneMotionRequest) -> ProviderResult:
        if not self.is_available():
            return _fail_result("kie_provider_unavailable", "KIE_API_KEY not configured")

        try:
            payload = self._build_payload(request)
        except ValueError as exc:
            return _fail_result("invalid_request", str(exc))

        estimated = self.estimate_cost_cents(request)

        async with self._client() as client:
            # Submit
            try:
                submit = await client.post(
                    KIE_CREATE_URL,
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=30.0,
                )
            except httpx.HTTPError as exc:
                logger.warning("[kie] submit transport error: %s", type(exc).__name__)
                return _fail_result("transport_error", type(exc).__name__)

            if submit.status_code == 402:
                return _fail_result("insufficient_credits", "KIE account has insufficient credits")
            if submit.status_code == 429:
                return _fail_result("rate_limited", "KIE rate limited")
            if submit.status_code >= 400:
                return _fail_result(
                    f"http_{submit.status_code}",
                    _safe_error_snippet(submit.text),
                )

            body = _safe_json(submit)
            if not body or body.get("code") != 200:
                return _fail_result(
                    "kie_create_failed",
                    _safe_error_snippet(str(body)),
                )
            task_id = ((body.get("data") or {}).get("taskId") or "").strip()
            if not task_id:
                return _fail_result("missing_task_id", "KIE createTask returned no taskId")

            # Poll to terminal state
            terminal = await self._poll_to_terminal(client, task_id)

        result = self._normalize_terminal(
            terminal,
            task_id=task_id,
            requested_duration_ms=request.duration_ms,
            requested_resolution=request.resolution,
            estimated_cents=estimated,
        )
        return result

    # ---- Internals --------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            # Tests wrap this with an already-managed client; return an
            # async context manager that yields it without closing.
            return _PassthroughClient(self._injected_client)  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=15.0))

    def _build_payload(self, req: SceneMotionRequest) -> dict[str, Any]:
        """Translate a SceneMotionRequest into KIE createTask payload.

        Enforces mutual exclusivity BEFORE the HTTP call so bad requests
        never leave the process.
        """
        # ---- Validate scalar fields
        duration_s = round(req.duration_ms / 1000)
        if not (_MIN_DURATION_S <= duration_s <= _MAX_DURATION_S):
            raise ValueError(
                f"duration_ms={req.duration_ms} outside Seedance 2.5 range "
                f"({_MIN_DURATION_S}-{_MAX_DURATION_S}s)"
            )
        if req.resolution not in _ALLOWED_RESOLUTIONS:
            raise ValueError(
                f"resolution={req.resolution!r} not in Seedance 2.5 API schema "
                f"({sorted(_ALLOWED_RESOLUTIONS)}). 1080p/4K are marketing only."
            )
        if req.aspect_ratio not in _ALLOWED_ASPECTS:
            raise ValueError(
                f"aspect_ratio={req.aspect_ratio!r} not in {sorted(_ALLOWED_ASPECTS)}"
            )

        # ---- Validate mode-specific field combinations
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

        # ---- Assemble the input block. Only include populated fields so
        # we don't send explicit nulls that KIE could reject on schema
        # validation.
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

        payload: dict[str, Any] = {
            "model": KIE_MODEL_ID,
            "input": input_block,
        }
        if self._callback_url:
            payload["callBackUrl"] = self._callback_url
        return payload

    async def _poll_to_terminal(
        self, client: httpx.AsyncClient, task_id: str
    ) -> dict[str, Any]:
        """Poll recordInfo until the task reaches success/fail or times out."""
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
                    return {"code": 0, "state": "fail", "failMsg": "poll timeout"}
                await asyncio.sleep(KIE_POLL_INTERVAL_S)
                continue

            body = _safe_json(r) or {}
            last_body = body
            data = body.get("data") or {}
            state = (data.get("state") or "").lower()
            if state in _TERMINAL_STATES:
                return body

            if asyncio.get_event_loop().time() >= deadline:
                # Attach a synthetic terminal so callers get a clean fail.
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
                return _fail_result(
                    "empty_result_urls",
                    "KIE reported success but returned no resultUrls",
                    task_id=task_id,
                    estimated_cents=estimated_cents,
                )
            return ProviderResult(
                ok=True,
                provider="kie",
                model=KIE_MODEL_ID,
                status=ProviderStatus.SUCCEEDED,
                output_url=result_urls[0],
                external_task_id=task_id,
                duration_ms=requested_duration_ms,
                resolution=requested_resolution,
                estimated_cost_cents=estimated_cents,
                actual_cost_credits=_safe_float(data.get("creditsConsumed")),
                raw=_safe_raw(data),
            )
        # Failure branch
        return _fail_result(
            data.get("failCode") or "kie_task_failed",
            data.get("failMsg") or "KIE task reached fail state",
            task_id=task_id,
            estimated_cents=estimated_cents,
        )


# ---- Helpers (module-private) ----------------------------------------------


def _fail_result(
    code: str,
    message: str,
    *,
    task_id: Optional[str] = None,
    estimated_cents: int = 0,
) -> ProviderResult:
    return ProviderResult(
        ok=False,
        provider="kie",
        model=KIE_MODEL_ID,
        status=ProviderStatus.FAILED,
        output_url=None,
        external_task_id=task_id,
        estimated_cost_cents=estimated_cents,
        error=message,
        error_code=code,
    )


def _safe_json(response: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return None


def _safe_error_snippet(text: str) -> str:
    # Trim to a bounded length so a hostile upstream can't blow logs.
    return (text or "")[:400]


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_raw(data: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded subset of the KIE record for forensic storage.

    Deliberately drops ``param`` (contains the exact request we already
    know) and free-form debug fields to keep DB rows small.
    """
    keys = ("state", "resultJson", "costTime", "creditsConsumed", "failCode", "failMsg", "completeTime")
    return {k: data.get(k) for k in keys if k in data}


def _extract_result_urls(data: dict[str, Any]) -> list[str]:
    """Parse ``resultJson`` (a string) → list of URLs.

    KIE's recordInfo returns ``resultJson`` as a JSON-encoded string
    containing ``{"resultUrls": [...]}``. We tolerate the field also
    being an already-decoded dict, since some KIE responses do that.
    """
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
    """Wrap an already-managed httpx.AsyncClient for ``async with`` use.

    Exists so tests can inject a client without the provider closing it
    on exit (pytest fixtures own the client lifetime).
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *exc_info: Any) -> None:
        # Do NOT close — the caller owns the client.
        return None


__all__ = ["KieProvider", "KIE_MODEL_ID", "KIE_CREATE_URL", "KIE_RECORD_URL"]
