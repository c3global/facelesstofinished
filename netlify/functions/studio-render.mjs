import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement } from './_shared/store.mjs';
import {
  newJobId,
  writeJob,
  indexJob,
  hasActiveJob,
} from './_shared/studioJobs.mjs';

const VALID_MODES = new Set(['avatar', 'faceless']);
const VALID_ASPECTS = new Set(['9_16', '16_9']);

function estimateCostCents({ mode, script, prompts }) {
  const words = script.split(/\s+/).filter(Boolean).length;
  const seconds = (words / 150) * 60;
  if (mode === 'avatar') {
    return Math.round(30 + (seconds / 30) * 10);
  }
  return Math.round(10 + prompts.length * 5);
}

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const allowed = await hasEntitlement(session.email, 'studio').catch(() => false);
  if (!allowed) {
    return json({ error: 'entitlement_required', entitlement: 'studio' }, { status: 403 });
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }

  const mode = String(body.mode || '').toLowerCase();
  const aspect = String(body.aspect || '').replace(':', '_');
  const captions = Boolean(body.captions);
  const script = String(body.script || '').trim();
  const promptsIn = Array.isArray(body.prompts) ? body.prompts : [];
  const prompts = promptsIn
    .map((p) => String(p || '').trim())
    .filter(Boolean)
    .slice(0, 12);

  if (!VALID_MODES.has(mode)) return json({ error: 'invalid_mode' }, { status: 400 });
  if (!VALID_ASPECTS.has(aspect)) return json({ error: 'invalid_aspect' }, { status: 400 });
  if (script.length < 10) return json({ error: 'script_too_short' }, { status: 400 });
  if (script.length > 8000) return json({ error: 'script_too_long' }, { status: 400 });
  if (prompts.length < 1 || prompts.length > 12) {
    return json({ error: 'invalid_prompts_count' }, { status: 400 });
  }

  if (await hasActiveJob(session.email)) {
    return json({ error: 'job_in_progress' }, { status: 409 });
  }

  const jobId = newJobId();
  const now = new Date().toISOString();
  const job = {
    id: jobId,
    userEmail: session.email,
    mode,
    aspect,
    captions,
    script,
    prompts,
    status: 'queued',
    progress: 0,
    progressLabel: 'Queued',
    resultUrl: null,
    error: null,
    estimatedCostCents: estimateCostCents({ mode, script, prompts }),
    createdAt: now,
    completedAt: null,
  };

  await writeJob(job);
  await indexJob(job);

  // Trigger the background worker. Awaiting (rather than fire-and-forget)
  // ensures the runtime actually dispatches the request before this handler
  // returns — Netlify Functions kill in-flight async work on exit, which
  // was leaving jobs stuck in 'queued' forever. Background functions reply
  // 202 immediately so this await adds ~tens of ms, not seconds.
  const url = new URL(req.url);
  const bgUrl = `${url.protocol}//${url.host}/.netlify/functions/studio-render-background`;
  try {
    await fetch(bgUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId }),
    });
  } catch (err) {
    console.error('failed to trigger background:', err);
    // Don't fail the user's request — the job record exists; we just couldn't
    // hand it off. Surface this to the activity log so it isn't invisible.
  }

  return json({ jobId, estimatedCostCents: job.estimatedCostCents }, { status: 202 });
};
