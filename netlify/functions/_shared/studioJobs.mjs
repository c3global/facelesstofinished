import { getStore } from '@netlify/blobs';
import { normalizeEmail } from './auth.mjs';

const STORE_NAME = 'f48-studio-jobs';
const INDEX_KEY = 'index';
const MAX_INDEX = 200;
const MAX_UPDATE_RETRIES = 5;
const BACKOFF_MS = [50, 100, 200, 400, 800];

export const ACTIVE_STATUSES = ['queued', 'voiceover', 'visuals', 'composing', 'polling'];

export function jobsStore() {
  return getStore(STORE_NAME);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export function newJobId() {
  // ULID-like: 13-char timestamp + 10 random chars (lexicographically sortable).
  const ts = Date.now().toString(36).padStart(9, '0');
  const rand = Math.random().toString(36).slice(2, 12).padEnd(10, '0');
  return `${ts}${rand}`;
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
    const { data, etag } = await store.getWithMetadata(jobId, { type: 'json' })
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

// Index: small JSON keyed by 'index' holding [{id,userEmail,status,createdAt}, ...]
// Used for cheap lookups by user. Bounded by MAX_INDEX entries (oldest dropped).
async function readIndex() {
  try {
    const raw = await jobsStore().get(INDEX_KEY, { type: 'json' });
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

async function updateIndex(mutator) {
  const store = jobsStore();
  for (let attempt = 0; attempt < MAX_UPDATE_RETRIES; attempt += 1) {
    const { data, etag } = await store.getWithMetadata(INDEX_KEY, { type: 'json' })
      .then((r) => r || { data: null, etag: null })
      .catch(() => ({ data: null, etag: null }));
    const current = Array.isArray(data) ? data : [];
    const next = await mutator(current);
    if (next === undefined) return current;
    try {
      const opts = etag ? { onlyIfMatch: etag } : { onlyIfNew: true };
      const result = await store.setJSON(INDEX_KEY, next, opts);
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
  throw new Error('updateIndex: failed after retries');
}

export async function indexJob(job) {
  const email = normalizeEmail(job.userEmail);
  await updateIndex((items) => {
    const filtered = items.filter((j) => j.id !== job.id);
    filtered.push({
      id: job.id,
      userEmail: email,
      status: job.status,
      mode: job.mode,
      createdAt: job.createdAt,
    });
    if (filtered.length > MAX_INDEX) return filtered.slice(filtered.length - MAX_INDEX);
    return filtered;
  });
}

export async function updateIndexStatus(jobId, status) {
  await updateIndex((items) => {
    const next = items.map((j) => (j.id === jobId ? { ...j, status } : j));
    return next;
  });
}

export async function listUserJobs(email, limit = 10) {
  const norm = normalizeEmail(email);
  const items = await readIndex();
  const mine = items.filter((j) => j.userEmail === norm);
  // Sort by createdAt desc.
  mine.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
  return mine.slice(0, limit);
}

export async function hasActiveJob(email) {
  const norm = normalizeEmail(email);
  const items = await readIndex();
  return items.some((j) => j.userEmail === norm && ACTIVE_STATUSES.includes(j.status));
}
