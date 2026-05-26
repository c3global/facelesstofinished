import { getStore } from '@netlify/blobs';
import { normalizeEmail } from './auth.mjs';

const STORE_NAME = 'f48-buyers';
export const KNOWN_ENTITLEMENTS = ['base', 'shorts'];

export function buyers() {
  return getStore(STORE_NAME);
}

async function readRecord(email) {
  const key = normalizeEmail(email);
  if (!key) return null;
  const raw = await buyers().get(key, { type: 'json' });
  if (!raw) return null;
  // Backwards compatibility: pre-entitlement records are treated as base only.
  if (!Array.isArray(raw.entitlements)) {
    raw.entitlements = ['base'];
  }
  return raw;
}

async function writeRecord(email, record) {
  const key = normalizeEmail(email);
  if (!key) return;
  await buyers().setJSON(key, record);
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
  const existing = (await readRecord(email)) || {
    addedAt: new Date().toISOString(),
    entitlements: [],
  };
  const set = new Set(existing.entitlements || []);
  set.add(name);
  const updated = {
    ...existing,
    entitlements: Array.from(set),
    ...meta,
  };
  if (!updated.addedAt) updated.addedAt = new Date().toISOString();
  await writeRecord(email, updated);
}

export async function revokeEntitlement(email, name) {
  const existing = await readRecord(email);
  if (!existing) return;
  const set = new Set(existing.entitlements || []);
  set.delete(name);
  if (set.size === 0) {
    await removeBuyer(email);
    return;
  }
  await writeRecord(email, { ...existing, entitlements: Array.from(set) });
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
