import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement } from './_shared/store.mjs';
import { writeJob, newJobId } from './_shared/scriptJobs.mjs';

const VALID_PLATFORMS = new Set(['youtube', 'reels', 'tiktok']);

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  if (!process.env.ANTHROPIC_API_KEY) {
    return json({ error: 'server_misconfigured' }, { status: 500 });
  }

  const allowed = await hasEntitlement(session.email, 'shorts').catch(() => false);
  if (!allowed) {
    return json({ error: 'entitlement_required', entitlement: 'shorts' }, { status: 403 });
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }

  const sourceScript = String(body.sourceScript || '').trim();
  if (!sourceScript) return json({ error: 'source_required' }, { status: 400 });
  if (sourceScript.length > 30000) return json({ error: 'source_too_large' }, { status: 400 });

  const platform = VALID_PLATFORMS.has(body.platform) ? body.platform : 'youtube';
  const angle =
    typeof body.angle === 'string' && body.angle.trim()
      ? body.angle.trim().slice(0, 40)
      : 'curiosity';

  const jobId = newJobId();
  const now = new Date().toISOString();

  await writeJob({
    id: jobId,
    userEmail: session.email,
    kind: 'repurpose',
    mode: 'shorts',
    platform,
    angle,
    sourceScript,
    status: 'queued',
    text: '',
    error: null,
    createdAt: now,
    updatedAt: now,
    completedAt: null,
  });

  const workerUrl = new URL(
    '/.netlify/functions/repurpose-script-worker-background',
    req.url
  ).href;

  try {
    await fetch(workerUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId }),
    });
  } catch (err) {
    console.error('failed to dispatch repurpose worker:', err);
  }

  return json({ jobId, status: 'queued' });
};
