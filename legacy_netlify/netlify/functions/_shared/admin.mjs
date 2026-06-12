import crypto from 'node:crypto';
import { normalizeEmail, readSession, readCookies } from './auth.mjs';

function adminEmailSet() {
  const raw = process.env.ADMIN_EMAILS || '';
  return new Set(
    raw
      .split(',')
      .map((e) => normalizeEmail(e))
      .filter(Boolean)
  );
}

export function isAdminEmail(email) {
  const normalized = normalizeEmail(email);
  if (!normalized) return false;
  return adminEmailSet().has(normalized);
}

export function isAdmin(req) {
  // Primary: session-cookie email is in ADMIN_EMAILS.
  try {
    const session = readSession(readCookies(req));
    if (session && isAdminEmail(session.email)) return true;
  } catch {
    // ignore — fall through to token check
  }

  // Secondary fallback: legacy x-admin-token header.
  const expected = process.env.ADMIN_TOKEN;
  if (!expected) return false;
  const provided = req.headers.get('x-admin-token');
  if (!provided) return false;
  try {
    return crypto.timingSafeEqual(
      Buffer.from(expected, 'utf8'),
      Buffer.from(provided, 'utf8')
    );
  } catch {
    return false;
  }
}
