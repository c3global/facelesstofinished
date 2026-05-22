import { createSessionCookie, normalizeEmail } from './_shared/auth.mjs';
import { isBuyer } from './_shared/store.mjs';

export const handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }

  let body;
  try {
    body = JSON.parse(event.body || '{}');
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'invalid_json' }) };
  }

  const email = normalizeEmail(body.email);
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return {
      statusCode: 400,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'invalid_email' }),
    };
  }

  let ok;
  try {
    ok = await isBuyer(email);
  } catch (err) {
    console.error('auth-login isBuyer error:', err);
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'lookup_failed', message: String(err?.message || err) }),
    };
  }
  if (!ok) {
    return {
      statusCode: 403,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'not_a_buyer' }),
    };
  }

  return {
    statusCode: 200,
    headers: {
      'Content-Type': 'application/json',
      'Set-Cookie': createSessionCookie(email),
    },
    body: JSON.stringify({ email }),
  };
};
