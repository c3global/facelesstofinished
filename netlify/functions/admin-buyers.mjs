import { isAdmin, unauthorized } from './_shared/admin.mjs';
import { buyers, addBuyer, removeBuyer } from './_shared/store.mjs';
import { normalizeEmail } from './_shared/auth.mjs';

export const handler = async (event) => {
  if (!isAdmin(event)) return unauthorized();

  if (event.httpMethod === 'GET') {
    const store = buyers();
    const { blobs } = await store.list();
    const items = await Promise.all(
      (blobs || []).map(async (b) => {
        const meta = await store.get(b.key, { type: 'json' }).catch(() => null);
        return { email: b.key, ...(meta || {}) };
      })
    );
    items.sort((a, b) => (a.addedAt || '').localeCompare(b.addedAt || ''));
    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ buyers: items }),
    };
  }

  let body = {};
  try {
    body = JSON.parse(event.body || '{}');
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'invalid_json' }) };
  }
  const email = normalizeEmail(body.email);
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return { statusCode: 400, body: JSON.stringify({ error: 'invalid_email' }) };
  }

  if (event.httpMethod === 'POST') {
    await addBuyer(email, { source: 'admin' });
    return { statusCode: 200, body: JSON.stringify({ ok: true, action: 'added', email }) };
  }
  if (event.httpMethod === 'DELETE') {
    await removeBuyer(email);
    return { statusCode: 200, body: JSON.stringify({ ok: true, action: 'removed', email }) };
  }

  return { statusCode: 405, body: 'Method not allowed' };
};
