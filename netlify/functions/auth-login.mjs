import { createSessionCookie, normalizeEmail, json } from './_shared/auth.mjs';
import { isBuyer, listEntitlements, recordLogin } from './_shared/store.mjs';

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }

  const email = normalizeEmail(body.email);
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return json({ error: 'invalid_email' }, { status: 400 });
  }

  let ok;
  try {
    ok = await isBuyer(email);
  } catch (err) {
    console.error('auth-login isBuyer error:', err);
    return json({ error: 'lookup_failed', message: String(err?.message || err) }, { status: 500 });
  }

  if (!ok) return json({ error: 'not_a_buyer' }, { status: 403 });

  const entitlements = await listEntitlements(email).catch(() => ['base']);

  // Track login engagement. Don't fail the login if this errors.
  recordLogin(email).catch((err) => console.error('recordLogin error:', err));

  return json({ email, entitlements }, {
    status: 200,
    headers: { 'Set-Cookie': createSessionCookie(email) },
  });
};
