"""Scale-to-zero HMAC dispatcher for Faceless48 Cloud Run Jobs."""

from __future__ import annotations

import os
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request

from render_dispatch import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    verify_dispatch_signature,
)


DISPATCH_HMAC_KEY = os.environ.get("DISPATCH_HMAC_KEY", "")
CLOUD_RUN_PROJECT = os.environ.get("CLOUD_RUN_PROJECT", "")
CLOUD_RUN_REGION = os.environ.get("CLOUD_RUN_REGION", "us-east1")
CLOUD_RUN_JOB = os.environ.get("CLOUD_RUN_JOB", "faceless48-render-worker")
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)

app = FastAPI(
    title="Faceless48 Render Dispatcher",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def dispatch_configuration_valid() -> bool:
    return bool(DISPATCH_HMAC_KEY and CLOUD_RUN_PROJECT and CLOUD_RUN_REGION and CLOUD_RUN_JOB)


async def _access_token(client: httpx.AsyncClient) -> str:
    response = await client.get(
        METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("metadata server returned no access token")
    return token


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": dispatch_configuration_valid()}


@app.post("/dispatch", status_code=202)
async def dispatch(request: Request) -> dict[str, str | bool]:
    if not dispatch_configuration_valid():
        raise HTTPException(status_code=503, detail="Dispatcher is not configured")

    body = await request.body()
    timestamp = request.headers.get(TIMESTAMP_HEADER, "")
    signature = request.headers.get(SIGNATURE_HEADER, "")
    if not verify_dispatch_signature(
        DISPATCH_HMAC_KEY,
        timestamp,
        body,
        signature,
    ):
        raise HTTPException(status_code=403, detail="Invalid dispatch signature")

    try:
        payload = await request.json()
        job_id = str(UUID(str(payload["job_id"])))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid job id") from None

    run_url = (
        "https://run.googleapis.com/v2/projects/"
        f"{CLOUD_RUN_PROJECT}/locations/{CLOUD_RUN_REGION}/jobs/{CLOUD_RUN_JOB}:run"
    )
    overrides = {
        "overrides": {
            "containerOverrides": [
                {"args": ["--job-id", job_id]},
            ],
            "taskCount": 1,
        }
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            token = await _access_token(client)
            response = await client.post(
                run_url,
                json=overrides,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail="Worker launch failed") from exc

    operation_name = response.json().get("name", "")
    return {"accepted": True, "job_id": job_id, "operation": operation_name}
