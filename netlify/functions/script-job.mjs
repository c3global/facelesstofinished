import { readSession, readCookies, json, normalizeEmail } from './_shared/auth.mjs';
import { readJob } from './_shared/scriptJobs.mjs';

export default async (req) => {
  if (req.method !== 'GET') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const url = new URL(req.url);
  const jobId = url.searchParams.get('id');
  if (!jobId) return json({ error: 'id_required' }, { status: 400 });

  const job = await readJob(jobId);
  if (!job) return json({ error: 'not_found' }, { status: 404 });

  if (normalizeEmail(job.userEmail) !== normalizeEmail(session.email)) {
    return json({ error: 'forbidden' }, { status: 403 });
  }

  return json({
    id: job.id,
    status: job.status,
    text: job.text || '',
    error: job.error || null,
    createdAt: job.createdAt,
    completedAt: job.completedAt || null,
  });
};
