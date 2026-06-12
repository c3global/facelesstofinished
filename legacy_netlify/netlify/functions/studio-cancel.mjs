import { readSession, readCookies, json, normalizeEmail } from './_shared/auth.mjs';
import { isAdminEmail } from './_shared/admin.mjs';
import { readJob, updateJob, updateIndexStatus } from './_shared/studioJobs.mjs';
import { logActivity } from './_shared/activity.mjs';

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const url = new URL(req.url);
  const jobId = url.searchParams.get('jobId');
  if (!jobId) return json({ error: 'jobId_required' }, { status: 400 });

  const job = await readJob(jobId);
  if (!job) return json({ error: 'not_found' }, { status: 404 });

  const owner = normalizeEmail(job.userEmail) === normalizeEmail(session.email);
  if (!owner && !isAdminEmail(session.email)) {
    return json({ error: 'forbidden' }, { status: 403 });
  }

  if (job.status === 'complete' || job.status === 'failed') {
    return json({ ok: true, status: job.status });
  }

  await updateJob(jobId, (cur) => {
    if (!cur) return undefined;
    return {
      ...cur,
      status: 'failed',
      error: 'canceled by user',
      progressLabel: 'Canceled',
      completedAt: new Date().toISOString(),
    };
  });
  try { await updateIndexStatus(jobId, 'failed'); } catch {}

  logActivity({
    type: 'studio_render_failed',
    email: session.email,
    detail: { jobId, mode: job.mode, error: 'canceled by user' },
  }).catch(() => {});

  return json({ ok: true, status: 'failed' });
};
