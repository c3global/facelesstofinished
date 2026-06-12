import { readSession, readCookies, json } from './_shared/auth.mjs';
import { isAdminEmail } from './_shared/admin.mjs';
import { readJob } from './_shared/studioJobs.mjs';
import { normalizeEmail } from './_shared/auth.mjs';

export default async (req) => {
  if (req.method !== 'GET') return new Response('Method not allowed', { status: 405 });

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

  return json({
    jobId: job.id,
    status: job.status,
    progress: job.progress,
    progressLabel: job.progressLabel,
    resultUrl: job.resultUrl,
    error: job.error,
    mode: job.mode,
    aspect: job.aspect,
    captions: job.captions,
    createdAt: job.createdAt,
    completedAt: job.completedAt,
  });
};
