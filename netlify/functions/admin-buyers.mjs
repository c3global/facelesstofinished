import { isAdmin } from './_shared/admin.mjs';
import {
  buyers,
  grantEntitlement,
  revokeEntitlement,
  removeBuyer,
  KNOWN_ENTITLEMENTS,
} from './_shared/store.mjs';
import { normalizeEmail, json } from './_shared/auth.mjs';

export default async (req) => {
  if (!isAdmin(req)) return json({ error: 'unauthorized' }, { status: 401 });

  const url = new URL(req.url);
  const action = url.searchParams.get('action');

  if (req.method === 'GET') {
    try {
      const store = buyers();
      const result = await store.list();
      const blobsList = result?.blobs || [];
      const items = await Promise.all(
        blobsList.map(async (b) => {
          const meta = await store.get(b.key, { type: 'json' }).catch(() => null);
          const ents = Array.isArray(meta?.entitlements) ? meta.entitlements : ['base'];
          return { email: b.key, ...(meta || {}), entitlements: ents };
        })
      );
      items.sort((a, b) => (a.addedAt || '').localeCompare(b.addedAt || ''));
      return json({ buyers: items, knownEntitlements: KNOWN_ENTITLEMENTS });
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
    // POST = add (optional entitlements list, defaults to ["base"])
    if (req.method === 'POST' && !action) {
      const requested = Array.isArray(body.entitlements) ? body.entitlements : ['base'];
      const ents = requested.filter((e) => KNOWN_ENTITLEMENTS.includes(e));
      const toGrant = ents.length ? ents : ['base'];
      for (const ent of toGrant) {
        await grantEntitlement(email, ent, { source: 'admin' });
      }
      return json({ ok: true, action: 'added', email, entitlements: toGrant });
    }

    // POST ?action=grant — grant a single entitlement
    if (req.method === 'POST' && action === 'grant') {
      const name = String(body.entitlement || '');
      if (!KNOWN_ENTITLEMENTS.includes(name)) {
        return json({ error: 'invalid_entitlement' }, { status: 400 });
      }
      await grantEntitlement(email, name, { source: 'admin' });
      return json({ ok: true, action: 'granted', email, entitlement: name });
    }

    // POST ?action=revoke — revoke a single entitlement (does not remove buyer unless last)
    if (req.method === 'POST' && action === 'revoke') {
      const name = String(body.entitlement || '');
      if (!KNOWN_ENTITLEMENTS.includes(name)) {
        return json({ error: 'invalid_entitlement' }, { status: 400 });
      }
      await revokeEntitlement(email, name);
      return json({ ok: true, action: 'revoked', email, entitlement: name });
    }

    // DELETE = remove the whole buyer
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
