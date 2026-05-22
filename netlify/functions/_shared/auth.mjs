import crypto from 'node:crypto';

const COOKIE_NAME = 'f48_session';
const SESSION_TTL_DAYS = 30;

function getSecret() {
  const s = process.env.SESSION_SECRET || process.env.PINBALL_WEBHOOK_TOKEN;
  if (!s) throw new Error('SESSION_SECRET is not set');
  return s;
}

function sign(payload) {
  return crypto.createHmac('sha256', getSecret()).update(payload).digest('hex');
}

export function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase();
}

export function createSessionCookie(email) {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_DAYS * 24 * 60 * 60;
  const payload = `${Buffer.from(email).toString('base64url')}.${exp}`;
  const sig = sign(payload);
  const value = `${payload}.${sig}`;
  const maxAge = SESSION_TTL_DAYS * 24 * 60 * 60;
  return `${COOKIE_NAME}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}

export function clearSessionCookie() {
  return `${COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
}

export function readSession(cookieHeader) {
  if (!cookieHeader) return null;
  const cookies = cookieHeader.split(';').map((c) => c.trim());
  const raw = cookies.find((c) => c.startsWith(`${COOKIE_NAME}=`));
  if (!raw) return null;
  const value = raw.slice(COOKIE_NAME.length + 1);
  const parts = value.split('.');
  if (parts.length !== 3) return null;
  const [emailB64, expStr, sig] = parts;
  let expected;
  try {
    expected = sign(`${emailB64}.${expStr}`);
  } catch {
    return null;
  }
  try {
    if (!crypto.timingSafeEqual(Buffer.from(sig, 'hex'), Buffer.from(expected, 'hex'))) {
      return null;
    }
  } catch {
    return null;
  }
  const exp = parseInt(expStr, 10);
  if (!Number.isFinite(exp) || exp * 1000 < Date.now()) return null;
  const email = Buffer.from(emailB64, 'base64url').toString('utf8');
  return { email, exp };
}

export function readCookies(req) {
  return req.headers.get('cookie') || '';
}

export function json(body, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set('Content-Type', 'application/json');
  return new Response(JSON.stringify(body), { ...init, headers });
}
