import { getStore } from '@netlify/blobs';
import { normalizeEmail } from './auth.mjs';

const STORE_NAME = 'f48-buyers';

export function buyers() {
  return getStore({ name: STORE_NAME, consistency: 'strong' });
}

export async function isBuyer(email) {
  const key = normalizeEmail(email);
  if (!key) return false;
  const record = await buyers().get(key);
  return record !== null && record !== undefined;
}

export async function addBuyer(email, meta = {}) {
  const key = normalizeEmail(email);
  if (!key) return;
  await buyers().setJSON(key, { addedAt: new Date().toISOString(), ...meta });
}

export async function removeBuyer(email) {
  const key = normalizeEmail(email);
  if (!key) return;
  await buyers().delete(key);
}
