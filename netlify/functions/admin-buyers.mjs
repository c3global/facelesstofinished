import { isAdmin } from './_shared/admin.mjs';
import { buyers, addBuyer, removeBuyer } from './_shared/store.mjs';
import { normalizeEmail, json } from './_shared/auth.mjs';

export default async (req) => {
  if (!isAdmin(req)) return json({ error: 'unauthorized' }, { status: 401 });

  if (req.method === 'GET') {
    try {
      const store = buyers();
      const result = await store.list();
      const blobsList = result?.blobs || [];
      const items = await Promise.all(
        blobsList.map(async (b) => {
          const meta = await store.get(b.key, { type: 'json' }).catch(() => null);
          return { email: b.key, ...(meta || {}) };
        })
      );
      items.sort((a, b) => (a.addedAt || '').localeCompare(b.addedAt || ''));
      return json({ buyers: items });
    } catch (err) {
      console.error('admin-buyers list error:', err);
      return json({ error: 'list_failed', message: String(err?.message || err) }, { status: 500 });
    }
  }

  let body = {};
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }
  const email = normalizeEmail(body.email);
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return json({ error: 'invalid_email' }, { status: 400 });
  }

  try {
    if (req.method === 'POST') {
      await addBuyer(email, { source: 'admin' });
      return json({ ok: true, action: 'added', email });
    }
    if (req.method === 'DELETE') {
      await removeBuyer(email);
      return json({ ok: true, action: 'removed', email });
    }
  } catch (err) {
    console.error('admin-buyers write error:', err);
    return json({ error: 'write_failed', message: String(err?.message || err) }, { status: 500 });
  }

  return new Response('Method not allowed', { status: 405 });
};
