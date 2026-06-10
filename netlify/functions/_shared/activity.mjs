import { getStore } from '@netlify/blobs';

// Append-only rolling activity log. Single blob key stores a JSON array.
// Oldest entries drop off once we exceed MAX_ENTRIES.
const LOG_STORE_NAME = 'f48-activity';
const LOG_KEY = 'activity-log';
const PAYLOAD_STORE_NAME = 'f48-webhook-payloads';
const MAX_ENTRIES = 500;
const MAX_UPDATE_RETRIES = 5;
const BACKOFF_MS = [50, 100, 200, 400, 800];

export const ACTIVITY_TYPES = [
  'webhook',
  'webhook_failed',
  'grant',
  'revoke',
  'remove',
  'add',
];

function logStore() {
  return getStore(LOG_STORE_NAME);
}

function payloadStore() {
  // Raw payloads kept here keyed by activity entry id so /replay can re-fire them.
  // No active TTL — Netlify Blobs has no TTL; rotate manually if it gets large.
  return getStore(PAYLOAD_STORE_NAME);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// updateRecord-style etag retry — mirrors store.mjs so concurrent appends are safe.
async function updateLog(mutator) {
  const store = logStore();
  for (let attempt = 0; attempt < MAX_UPDATE_RETRIES; attempt += 1) {
    const { data, etag } = await store
      .getWithMetadata(LOG_KEY, { type: 'json' })
      .then((r) => r || { data: null, etag: null })
      .catch(() => ({ data: null, etag: null }));

    const current = Array.isArray(data) ? data : [];
    const next = await mutator(current);
    if (next === undefined) return current;

    try {
      const opts = etag ? { onlyIfMatch: etag } : { onlyIfNew: true };
      const result = await store.setJSON(LOG_KEY, next, opts);
      if (result && result.modified === false) {
        await sleep(BACKOFF_MS[attempt] || 800);
        continue;
      }
      return next;
    } catch (err) {
      const msg = String(err?.message || err);
      if (/precondition|etag|conflict|conditional/i.test(msg) && attempt < MAX_UPDATE_RETRIES - 1) {
        await sleep(BACKOFF_MS[attempt] || 800);
        continue;
      }
      if (attempt < MAX_UPDATE_RETRIES - 1) {
        await sleep(BACKOFF_MS[attempt] || 800);
        continue;
      }
      throw err;
    }
  }
  throw new Error('updateLog: failed after retries');
}

// Append a single entry. Fire-and-forget safe: any internal error is swallowed
// and logged so a failing log write never breaks a webhook/admin call.
export async function logActivity(entry) {
  try {
    const id = entry?.id || newId();
    const ts = entry?.ts || new Date().toISOString();
    const record = {
      id,
      ts,
      type: entry?.type || 'webhook',
      email: entry?.email ?? null,
      actor: entry?.actor ?? null,
      detail: entry?.detail || {},
    };
    await updateLog((current) => {
      const next = [...current, record];
      if (next.length > MAX_ENTRIES) {
        return next.slice(next.length - MAX_ENTRIES);
      }
      return next;
    });
    return record;
  } catch (err) {
    console.error('logActivity failed:', err);
    return null;
  }
}

export async function listActivity({ limit = 100, type, sinceMs } = {}) {
  try {
    const raw = (await logStore().get(LOG_KEY, { type: 'json' })) || [];
    let items = Array.isArray(raw) ? raw : [];
    if (type) items = items.filter((e) => e.type === type);
    if (Number.isFinite(sinceMs)) {
      items = items.filter((e) => {
        const ms = Date.parse(e.ts);
        return Number.isFinite(ms) && ms >= sinceMs;
      });
    }
    // Most recent first.
    items = items.slice().reverse();
    const cap = Math.min(Math.max(1, limit | 0), MAX_ENTRIES);
    return items.slice(0, cap);
  } catch (err) {
    console.error('listActivity failed:', err);
    return [];
  }
}

export async function getActivityRaw() {
  try {
    const raw = (await logStore().get(LOG_KEY, { type: 'json' })) || [];
    return Array.isArray(raw) ? raw : [];
  } catch (err) {
    console.error('getActivityRaw failed:', err);
    return [];
  }
}

// Store the raw webhook payload (plus a tiny envelope) so we can replay it.
export async function storeWebhookPayload(activityId, payload, meta = {}) {
  try {
    await payloadStore().setJSON(activityId, {
      storedAt: new Date().toISOString(),
      meta,
      payload,
    });
  } catch (err) {
    console.error('storeWebhookPayload failed:', err);
  }
}

export async function getWebhookPayload(activityId) {
  try {
    return await payloadStore().get(activityId, { type: 'json' });
  } catch (err) {
    console.error('getWebhookPayload failed:', err);
    return null;
  }
}
