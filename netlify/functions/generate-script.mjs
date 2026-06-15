import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement } from './_shared/store.mjs';
import { writeJob, newJobId } from './_shared/scriptJobs.mjs';

const VALID_LENGTHS = new Set(['short', 'medium', 'long']);
const VALID_PLATFORMS = new Set(['youtube', 'reels', 'tiktok']);

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  if (!process.env.ANTHROPIC_API_KEY) {
    return json({ error: 'server_misconfigured' }, { status: 500 });
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }

  const topic = String(body.topic || '').trim();
  if (!topic) return json({ error: 'topic_required' }, { status: 400 });

  const mode = body.mode === 'shorts' ? 'shorts' : 'long';
  const requiredEntitlement = mode === 'shorts' ? 'shorts' : 'base';

  const allowed = await hasEntitlement(session.email, requiredEntitlement).catch(() => false);
  if (!allowed) {
    return json(
      { error: 'entitlement_required', entitlement: requiredEntitlement },
      { status: 403 }
    );
  }

  const length = VALID_LENGTHS.has(body.length) ? body.length : 'medium';
  const platform = VALID_PLATFORMS.has(body.platform) ? body.platform : 'youtube';
  const angle =
    typeof body.angle === 'string' && body.angle.trim()
      ? body.angle.trim().slice(0, 40)
      : null;

  const jobId = newJobId();
  const now = new Date().toISOString();

  await writeJob({
    id: jobId,
    userEmail: session.email,
    mode,
    length,
    platform,
    angle,
    topic,
    includeHooks: body.includeHooks !== false,
    includeBRoll: body.includeBRoll !== false,
    includeNotes: body.includeNotes !== false,
    status: 'queued',
    text: '',
    error: null,
    createdAt: now,
    updatedAt: now,
    completedAt: null,
  });

  const workerUrl = new URL(
    '/.netlify/functions/generate-script-worker-background',
    req.url
  ).href;

  try {
    await fetch(workerUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId }),
    });
  } catch (err) {
    console.error('failed to dispatch background worker:', err);
  }

  return json({ jobId, status: 'queued' });
};
