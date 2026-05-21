import crypto from 'node:crypto';

export function isAdmin(event) {
  const expected = process.env.ADMIN_TOKEN;
  if (!expected) return false;
  const provided =
    event.headers?.['x-admin-token'] ||
    event.headers?.['X-Admin-Token'] ||
    null;
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

export function unauthorized() {
  return {
    statusCode: 401,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ error: 'unauthorized' }),
  };
}
