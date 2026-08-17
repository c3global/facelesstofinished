# Faceless48 isolated render worker

This directory prepares the existing Studio renderer for Google Cloud Run
Jobs. It does **not** deploy anything, enable APIs, or incur charges.

## Boundary

The customer application remains unchanged. The API continues creating a
MongoDB `renders` document and Studio continues polling it. When the API has
`RENDER_EXECUTION_BACKEND=cloud_run_queue`, Faceless submissions remain in
`queued` status instead of starting an in-process task. A Cloud Scheduler
invocation wakes this worker once per minute; a MongoDB lease guarantees that
only one render runs at a time.

```python
asyncio.create_task(_run_render(job_id))
```

The worker selects the oldest queued Faceless job. Manual staging executions
may still provide `RENDER_JOB_ID`. It uses the same MongoDB, GridFS uploads,
providers, progress fields, quota refund logic, and R2 output.

## Safety rules

- Do not set `RENDER_EXECUTION_BACKEND=cloud_run_queue` until the scheduled
  worker is deployed and a staging render passes.
- Automatic retries remain `0` until paid calls have idempotency keys.
- One execution processes one render ID.
- A global Mongo lease serializes executions, and the per-job claim prevents a
  second execution from claiming the same queued job.
- Run `--probe` before enabling the scheduler. It checks MongoDB, ffmpeg,
  object storage, and required provider configuration without claiming a job
  or making a paid call.
- Secrets belong in Google Secret Manager, never GitHub or YAML.
- Timeline features remain disabled.

## Files

- `render-worker.Dockerfile` — Python 3.12 + ffmpeg image.
- `render-worker.Dockerfile.dockerignore` — excludes secrets and unrelated apps.
- `../backend/requirements-worker.txt` — public render-only dependencies; it
  intentionally excludes Emergent's private script/thumbnail integration.
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

Production cutover is one environment change on the existing API after the
scheduled worker passes staging: `RENDER_EXECUTION_BACKEND=cloud_run_queue`.
