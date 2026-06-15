import { getStore } from '@netlify/blobs';

const STORE_NAME = 'f48-script-jobs';
const MAX_UPDATE_RETRIES = 5;
const BACKOFF_MS = [50, 100, 200, 400, 800];

export function jobsStore() {
  return getStore(STORE_NAME);
}

export function newJobId() {
  const ts = Date.now().toString(36).padStart(9, '0');
  const rand = Math.random().toString(36).slice(2, 12).padEnd(10, '0');
  return `${ts}${rand}`;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export async function readJob(jobId) {
  if (!jobId) return null;
  try {
    return (await jobsStore().get(jobId, { type: 'json' })) || null;
  } catch {
    return null;
  }
}

export async function writeJob(job) {
  if (!job?.id) throw new Error('writeJob: job.id required');
  await jobsStore().setJSON(job.id, job);
  return job;
}

export async function updateJob(jobId, mutator) {
  const store = jobsStore();
  for (let attempt = 0; attempt < MAX_UPDATE_RETRIES; attempt += 1) {
    const { data, etag } = await store
      .getWithMetadata(jobId, { type: 'json' })
      .then((r) => r || { data: null, etag: null })
      .catch(() => ({ data: null, etag: null }));
    const current = data || null;
    const next = await mutator(current);
    if (next === undefined) return current;
    try {
      const opts = etag ? { onlyIfMatch: etag } : { onlyIfNew: true };
      const result = await store.setJSON(jobId, next, opts);
      if (result && result.modified === false) {
        await sleep(BACKOFF_MS[attempt] || 800);
        continue;
      }
      return next;
    } catch (err) {
      if (attempt < MAX_UPDATE_RETRIES - 1) {
        await sleep(BACKOFF_MS[attempt] || 800);
        continue;
      }
      throw err;
    }
  }
  throw new Error('updateJob: failed after retries');
}

export async function deleteJob(jobId) {
  try {
    await jobsStore().delete(jobId);
  } catch {
    /* ignore */
  }
}
