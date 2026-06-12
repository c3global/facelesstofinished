import { readSession, readCookies, json, normalizeEmail } from './_shared/auth.mjs';
import { isAdminEmail } from './_shared/admin.mjs';
import { readJob, deleteJob, ACTIVE_STATUSES } from './_shared/studioJobs.mjs';
import { logActivity } from './_shared/activity.mjs';

async function readJobId(req) {
  const url = new URL(req.url);
  const qid = url.searchParams.get('jobId');
  if (qid) return qid;
  try {
    const body = await req.json();
    return body?.jobId || null;
  } catch {
    return null;
  }
}

export default async (req) => {
  if (req.method !== 'DELETE' && req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 });
  }

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const jobId = await readJobId(req);
  if (!jobId) return json({ error: 'jobId_required' }, { status: 400 });

  const job = await readJob(jobId);
  if (!job) return json({ error: 'not_found' }, { status: 404 });

  const owner = normalizeEmail(job.userEmail) === normalizeEmail(session.email);
  if (!owner && !isAdminEmail(session.email)) {
    return json({ error: 'forbidden' }, { status: 403 });
  }

  if (ACTIVE_STATUSES.includes(job.status)) {
    return json(
      { error: 'job_in_progress', message: 'Cancel this render before deleting it.' },
      { status: 409 }
    );
  }

  await deleteJob(jobId);

  logActivity({
    type: 'studio_render_deleted',
    email: session.email,
    detail: { jobId },
  }).catch(() => {});

  return json({ ok: true });
};
