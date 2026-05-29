import { getStore } from '@netlify/blobs';
import { normalizeEmail } from './auth.mjs';

const STORE_NAME = 'f48-buyers';
export const KNOWN_ENTITLEMENTS = ['base', 'shorts'];

const MAX_UPDATE_RETRIES = 5;
const BACKOFF_MS = [50, 100, 200, 400, 800];

export function buyers() {
  return getStore(STORE_NAME);
}

function normalizeForRead(raw) {
  if (!raw) return null;
  // Backwards compatibility: pre-entitlement records are treated as base only.
  if (!Array.isArray(raw.entitlements)) {
    raw.entitlements = ['base'];
  }
  return raw;
}

async function readRecord(email) {
  const key = normalizeEmail(email);
  if (!key) return null;
  const raw = await buyers().get(key, { type: 'json' });
  return normalizeForRead(raw);
}

// Optimistic-locking read-modify-write. The mutator receives the current
// record (or null if missing) and must return:
//   - an updated record object to write
//   - null to delete the record
//   - undefined to leave it unchanged (no write)
// Uses Netlify Blobs etag-based conditional writes. Retries on conflict.
async function updateRecord(email, mutator) {
  const key = normalizeEmail(email);
  if (!key) return null;
  const store = buyers();

  for (let attempt = 0; attempt < MAX_UPDATE_RETRIES; attempt += 1) {
    const { data, etag } = await store.getWithMetadata(key, { type: 'json' })
      .then((r) => r || { data: null, etag: null })
      .catch(() => ({ data: null, etag: null }));

    const current = normalizeForRead(data);
    const next = await mutator(current);

    if (next === undefined) return current; // no-op

    if (next === null) {
      // Delete branch — etag conditional delete isn't broadly supported,
      // so a plain delete is the closest we have.
      await store.delete(key);
      return null;
    }

    try {
      const opts = etag ? { onlyIfMatch: etag } : { onlyIfNew: true };
      const result = await store.setJSON(key, next, opts);
      // setJSON returns { modified: false } when the conditional write was
      // rejected. Older SDKs may instead throw — handled in catch below.
      if (result && result.modified === false) {
        await sleep(BACKOFF_MS[attempt] || 800);
        continue;
      }
      return next;
    } catch (err) {
      // Treat conditional-write rejection as a retryable conflict.
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
  throw new Error(`updateRecord: failed after ${MAX_UPDATE_RETRIES} retries for ${key}`);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export async function isBuyer(email) {
  const record = await readRecord(email);
  return record !== null;
}

export async function listEntitlements(email) {
  const record = await readRecord(email);
  return record?.entitlements || [];
}

export async function hasEntitlement(email, name) {
  const ents = await listEntitlements(email);
  return ents.includes(name);
}

export async function grantEntitlement(email, name, meta = {}) {
  const key = normalizeEmail(email);
  if (!key || !name) return;
  await updateRecord(email, (existing) => {
    const base = existing || {
      addedAt: new Date().toISOString(),
      entitlements: [],
    };
    const set = new Set(base.entitlements || []);
    set.add(name);

    // Revenue tracking: dedupe orders by id, sum total_amount when known.
    const seenOrderIds = Array.isArray(base.seenOrderIds) ? [...base.seenOrderIds] : [];
    let totalSpendCents = Number.isFinite(base.totalSpendCents) ? base.totalSpendCents : 0;
    const incomingOrderId = meta?.orderId;
    const incomingTotal = Number(meta?.orderTotalCents);
    if (incomingOrderId && !seenOrderIds.includes(incomingOrderId)) {
      seenOrderIds.push(incomingOrderId);
      if (Number.isFinite(incomingTotal) && incomingTotal > 0) {
        totalSpendCents += incomingTotal;
      }
    }

    // Strip the helper-only field from meta before merging.
    const { orderTotalCents: _omit, ...metaForRecord } = meta || {};

    const updated = {
      ...base,
      entitlements: Array.from(set),
      ...metaForRecord,
      seenOrderIds,
      totalSpendCents,
    };
    if (!updated.addedAt) updated.addedAt = new Date().toISOString();
    return updated;
  });
}

export async function recordLogin(email) {
  const key = normalizeEmail(email);
  if (!key) return;
  await updateRecord(email, (existing) => {
    if (!existing) return undefined;
    return {
      ...existing,
      lastLoginAt: new Date().toISOString(),
      loginCount: (Number.isFinite(existing.loginCount) ? existing.loginCount : 0) + 1,
    };
  });
}

export async function recordScriptGeneration(email) {
  const key = normalizeEmail(email);
  if (!key) return;
  await updateRecord(email, (existing) => {
    if (!existing) return undefined;
    const now = new Date().toISOString();
    return {
      ...existing,
      scriptCount: (Number.isFinite(existing.scriptCount) ? existing.scriptCount : 0) + 1,
      firstUseAt: existing.firstUseAt || now,
    };
  });
}

export async function recordShortsGeneration(email) {
  const key = normalizeEmail(email);
  if (!key) return;
  await updateRecord(email, (existing) => {
    if (!existing) return undefined;
    const now = new Date().toISOString();
    return {
      ...existing,
      shortsCount: (Number.isFinite(existing.shortsCount) ? existing.shortsCount : 0) + 1,
      firstUseAt: existing.firstUseAt || now,
    };
  });
}

export async function revokeEntitlement(email, name) {
  await updateRecord(email, (existing) => {
    if (!existing) return undefined;
    const set = new Set(existing.entitlements || []);
    set.delete(name);
    if (set.size === 0) return null; // delete record
    return { ...existing, entitlements: Array.from(set) };
  });
}

// Legacy helpers kept so older call sites keep compiling. They now grant/revoke
// the `base` entitlement by default — the same effect they used to have.
export async function addBuyer(email, meta = {}) {
  await grantEntitlement(email, 'base', meta);
}

export async function removeBuyer(email) {
  const key = normalizeEmail(email);
  if (!key) return;
  await buyers().delete(key);
}
