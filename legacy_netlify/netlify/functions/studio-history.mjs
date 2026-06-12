import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement } from './_shared/store.mjs';
import { listUserJobs, readJob } from './_shared/studioJobs.mjs';

export default async (req) => {
  if (req.method !== 'GET') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const allowed = await hasEntitlement(session.email, 'studio').catch(() => false);
  if (!allowed) {
    return json({ error: 'entitlement_required', entitlement: 'studio' }, { status: 403 });
  }

  const entries = await listUserJobs(session.email, 10);
  const jobs = await Promise.all(
    entries.map(async (e) => {
      const j = await readJob(e.id);
      if (!j) return null;
      return {
        id: j.id,
        mode: j.mode,
        aspect: j.aspect,
        captions: j.captions,
        status: j.status,
        progress: j.progress,
        progressLabel: j.progressLabel,
        resultUrl: j.resultUrl,
        error: j.error,
        scriptPreview: String(j.script || '').slice(0, 200),
        promptCount: Array.isArray(j.prompts) ? j.prompts.length : 0,
        estimatedCostCents: j.estimatedCostCents,
        createdAt: j.createdAt,
        completedAt: j.completedAt,
      };
    })
  );

  return json({ jobs: jobs.filter(Boolean) });
};
