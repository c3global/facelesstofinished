import { isAdmin } from './_shared/admin.mjs';
import {
  buyers,
  grantEntitlement,
  revokeEntitlement,
  removeBuyer,
  KNOWN_ENTITLEMENTS,
} from './_shared/store.mjs';
import { normalizeEmail, json, readSession, readCookies } from './_shared/auth.mjs';
import { logActivity } from './_shared/activity.mjs';

export default async (req) => {
  if (!isAdmin(req)) return json({ error: 'unauthorized' }, { status: 401 });
  const sessionEmail = (() => {
    try { return readSession(readCookies(req))?.email || null; } catch { return null; }
  })();

  const url = new URL(req.url);
  const action = url.searchParams.get('action');

  if (req.method === 'GET') {
    try {
      const store = buyers();
      const result = await store.list();
      const blobsList = result?.blobs || [];
      const now = Date.now();
      const DAY = 24 * 60 * 60 * 1000;

      const rawItems = await Promise.all(
        blobsList.map(async (b) => {
          const meta = await store.get(b.key, { type: 'json' }).catch(() => null);
          const ents = Array.isArray(meta?.entitlements) ? meta.entitlements : ['base'];
          return { email: b.key, ...(meta || {}), entitlements: ents };
        })
      );

      // Derived per-buyer fields + aggregate accumulators.
      const byEntitlement = Object.fromEntries(KNOWN_ENTITLEMENTS.map((e) => [e, 0]));
      let activeLast7d = 0;
      let activeLast30d = 0;
      let neverLoggedIn = 0;
      let scriptsGenerated = 0;
      let shortsGenerated = 0;
      let activatedCustomers = 0;
      let stuckCustomers = 0;
      let revenueCents = 0;
      let baseCount = 0;
      let baseAndShortsCount = 0;

      const signupBuckets = new Map(); // YYYY-MM-DD -> count

      const items = rawItems.map((b) => {
        const ents = b.entitlements;
        for (const e of ents) {
          if (e in byEntitlement) byEntitlement[e] += 1;
        }
        const hasBase = ents.includes('base');
        const hasShorts = ents.includes('shorts');
        if (hasBase) baseCount += 1;
        if (hasBase && hasShorts) baseAndShortsCount += 1;

        const lastLoginMs = b.lastLoginAt ? Date.parse(b.lastLoginAt) : NaN;
        let daysSinceLastLogin = null;
        if (Number.isFinite(lastLoginMs)) {
          daysSinceLastLogin = Math.floor((now - lastLoginMs) / DAY);
          if (now - lastLoginMs <= 7 * DAY) activeLast7d += 1;
          if (now - lastLoginMs <= 30 * DAY) activeLast30d += 1;
        } else {
          neverLoggedIn += 1;
        }

        const addedMs = b.addedAt ? Date.parse(b.addedAt) : NaN;
        if (Number.isFinite(addedMs)) {
          if (!Number.isFinite(lastLoginMs) && now - addedMs >= 7 * DAY) {
            stuckCustomers += 1;
          }
          const day = new Date(addedMs).toISOString().slice(0, 10);
          signupBuckets.set(day, (signupBuckets.get(day) || 0) + 1);
        }

        const scriptCount = Number.isFinite(b.scriptCount) ? b.scriptCount : 0;
        const shortsCount = Number.isFinite(b.shortsCount) ? b.shortsCount : 0;
        scriptsGenerated += scriptCount;
        shortsGenerated += shortsCount;

        let daysToFirstUse = null;
        if (b.firstUseAt) {
          activatedCustomers += 1;
          const firstUseMs = Date.parse(b.firstUseAt);
          if (Number.isFinite(firstUseMs) && Number.isFinite(addedMs)) {
            daysToFirstUse = Math.max(0, Math.floor((firstUseMs - addedMs) / DAY));
          }
        }

        const spend = Number.isFinite(b.totalSpendCents) ? b.totalSpendCents : 0;
        revenueCents += spend;

        return {
          ...b,
          scriptCount,
          shortsCount,
          loginCount: Number.isFinite(b.loginCount) ? b.loginCount : 0,
          totalSpendCents: spend,
          seenOrderIds: Array.isArray(b.seenOrderIds) ? b.seenOrderIds : [],
          daysSinceLastLogin,
          daysToFirstUse,
        };
      });

      items.sort((a, b) => (a.addedAt || '').localeCompare(b.addedAt || ''));

      // signupsPerDay — last 30 days inclusive of today, oldest first, padded with 0.
      const signupsPerDay = [];
      for (let i = 29; i >= 0; i -= 1) {
        const d = new Date(now - i * DAY);
        const key = d.toISOString().slice(0, 10);
        signupsPerDay.push({ date: key, count: signupBuckets.get(key) || 0 });
      }

      const conversionToShorts = baseCount > 0 ? baseAndShortsCount / baseCount : 0;

      const totals = {
        customers: items.length,
        byEntitlement,
        activeLast7d,
        activeLast30d,
        neverLoggedIn,
        scriptsGenerated,
        shortsGenerated,
        activatedCustomers,
        stuckCustomers,
        revenueCents,
        conversionToShorts,
      };

      return json({
        buyers: items,
        knownEntitlements: KNOWN_ENTITLEMENTS,
        totals,
        signupsPerDay,
      });
    } catch (err) {
      console.error('admin-buyers list error:', err);
      return json({ error: 'list_failed', message: String(err?.message || err) }, { status: 500 });
    }
  }

  // DELETE requests don't reliably carry JSON bodies through Netlify
  // Functions, so accept the email via query string as well as body.
  let body = {};
  if (req.method !== 'DELETE') {
    try {
      body = await req.json();
    } catch {
      return json({ error: 'invalid_json' }, { status: 400 });
    }
  }
  const emailFromQuery = url.searchParams.get('email');
  const email = normalizeEmail(emailFromQuery || body.email);
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
      await logActivity({
        type: 'add',
        email,
        actor: sessionEmail,
        detail: { entitlements: toGrant, source: 'admin' },
      });
      return json({ ok: true, action: 'added', email, entitlements: toGrant });
    }

    // POST ?action=grant — grant a single entitlement
    if (req.method === 'POST' && action === 'grant') {
      const name = String(body.entitlement || '');
      if (!KNOWN_ENTITLEMENTS.includes(name)) {
        return json({ error: 'invalid_entitlement' }, { status: 400 });
      }
      await grantEntitlement(email, name, { source: 'admin' });
      await logActivity({
        type: 'grant',
        email,
        actor: sessionEmail,
        detail: { entitlement: name, source: 'admin' },
      });
      return json({ ok: true, action: 'granted', email, entitlement: name });
    }

    // POST ?action=revoke — revoke a single entitlement (does not remove buyer unless last)
    if (req.method === 'POST' && action === 'revoke') {
      const name = String(body.entitlement || '');
      if (!KNOWN_ENTITLEMENTS.includes(name)) {
        return json({ error: 'invalid_entitlement' }, { status: 400 });
      }
      await revokeEntitlement(email, name);
      await logActivity({
        type: 'revoke',
        email,
        actor: sessionEmail,
        detail: { entitlement: name, source: 'admin' },
      });
      return json({ ok: true, action: 'revoked', email, entitlement: name });
    }

    // DELETE = remove the whole buyer (legacy path; the frontend prefers
    // POST ?action=delete since Netlify Functions doesn't reliably carry
    // a JSON body on DELETE).
    if (req.method === 'DELETE' || (req.method === 'POST' && action === 'delete')) {
      await removeBuyer(email);
      await logActivity({
        type: 'remove',
        email,
        actor: sessionEmail,
        detail: { source: 'admin' },
      });
      return json({ ok: true, action: 'removed', email });
    }
  } catch (err) {
    console.error('admin-buyers write error:', err);
    return json({ error: 'write_failed', message: String(err?.message || err) }, { status: 500 });
  }

  return new Response('Method not allowed', { status: 405 });
};
