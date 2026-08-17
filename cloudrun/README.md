# Faceless48 isolated render worker

This directory prepares the existing Studio renderer for Google Cloud Run
Jobs. It does **not** deploy anything, enable APIs, or incur charges.

## Boundary

The customer application remains unchanged. The API continues creating a
MongoDB `renders` document and Studio continues polling it. A future handoff
patch replaces only:

```python
asyncio.create_task(_run_render(job_id))
```

with an authenticated Cloud Run Job execution carrying `RENDER_JOB_ID` and a
unique `RENDER_EXECUTION_ID`. The worker uses the same MongoDB, GridFS uploads,
providers, progress fields, quota refund logic, and R2 output.

## Safety rules

- Do not enable Cloud Run dispatch until the API handoff patch is deployed.
  Running local and remote workers together could duplicate provider charges.
- Automatic retries remain `0` until paid calls have idempotency keys.
- One execution processes one render ID.
- The Mongo claim prevents a second execution claiming the same queued job.
- Secrets belong in Google Secret Manager, never GitHub or YAML.
- Timeline features remain disabled.

## Files

- `render-worker.Dockerfile` — Python 3.12 + ffmpeg image.
- `render-worker.Dockerfile.dockerignore` — excludes secrets and unrelated apps.
- `render-worker.env.example` — variable names and safe defaults only.
- `job.template.yaml` — non-deploying 2 CPU / 4 GiB / 60-minute template.
- `cloudbuild.render-worker.yaml` — build-and-push only; never deploys a job.
- `../backend/render_worker.py` — one-job process entry point.
- `../backend/render_worker_runtime.py` — testable claim/state helpers.

## Before first deployment

1. Link billing and configure a Cloud Run spend cap.
2. Confirm the MongoDB region, then choose the nearest Cloud Run region.
3. Create Artifact Registry and a least-privilege runtime service account.
4. Store credentials in Secret Manager.
5. Review the Cloud Build substitutions for the final region and repository.
6. Deploy a staging job with no production dispatcher attached.
7. Run mocked tests first, then one explicitly approved capped render.

The production dispatcher is intentionally not included in this foundation.
It must replace the current in-process call in one controlled deployment.
