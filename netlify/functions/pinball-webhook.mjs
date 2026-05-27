import crypto from 'node:crypto';
import { grantEntitlement, revokeEntitlement, KNOWN_ENTITLEMENTS } from './_shared/store.mjs';

// Map GHL/Pinball product IDs → app entitlements. Add a row here when you create a new product.
// Bumps and bonuses (Topic Vault, etc.) intentionally omitted — they're delivered separately, not as app entitlements.
const PRODUCT_ID_TO_ENTITLEMENT = {
  '01ks3pmetahzgx2mfg7q5crs0j': 'base',   // Faceless to Finished in 48
  '01ksgx97wad7vcc27ycvw0erg7': 'shorts', // Faceless Shorts (OTO + backend)
};

function verifyToken(req) {
  const expected = process.env.PINBALL_WEBHOOK_TOKEN;
  if (!expected) return false;
  const provided = new URL(req.url).searchParams.get('token');
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

function extractEmail(p) {
  return (
    p?.customer?.email ||
    p?.data?.customer?.email ||
    p?.data?.email ||
    p?.order?.customer?.email ||
    p?.data?.order?.customer?.email ||
    p?.email ||
    null
  );
}

function extractOrderId(p) {
  return (
    p?.order?.id ||
    p?.data?.order?.id ||
    p?.order_id ||
    p?.data?.order_id ||
    p?.id ||
    p?.data?.id ||
    null
  );
}

function extractEvent(p, req) {
  return (
    p?.event ||
    p?.type ||
    req.headers.get('x-pinball-event') ||
    req.headers.get('x-event-type') ||
    null
  );
}

function extractItems(p) {
  if (Array.isArray(p?.items)) return p.items;
  if (Array.isArray(p?.data?.items)) return p.data.items;
  if (Array.isArray(p?.order?.items)) return p.order.items;
  if (Array.isArray(p?.data?.order?.items)) return p.data.order.items;
  return [];
}

// Returns the entitlement codes implied by a webhook payload. Prefers items[] (GHL/Pinball
// funnel format) since one funnel completion can grant multiple entitlements at once.
// Falls back to the legacy ?product= query param if no items array is present.
function resolveEntitlements(payload, productParamRaw) {
  const items = extractItems(payload);
  const matched = new Set();
  for (const it of items) {
    const id = it?.product_id;
    if (id && PRODUCT_ID_TO_ENTITLEMENT[id]) matched.add(PRODUCT_ID_TO_ENTITLEMENT[id]);
  }
  if (matched.size > 0) return [...matched];
  const fallback = KNOWN_ENTITLEMENTS.includes(productParamRaw) ? productParamRaw : 'base';
  return [fallback];
}

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  if (!verifyToken(req)) {
    return new Response('Invalid or missing token', { status: 401 });
  }

  let payload;
  try {
    payload = await req.json();
  } catch {
    return new Response('Invalid JSON', { status: 400 });
  }

  const eventType = extractEvent(payload, req);
  const email = extractEmail(payload);
  const orderId = extractOrderId(payload);
  const productParam = new URL(req.url).searchParams.get('product') || 'base';
  const entitlements = resolveEntitlements(payload, productParam);

  if (!email) {
    console.error('pinball-webhook: no email in payload', JSON.stringify(payload).slice(0, 500));
    return new Response('No email in payload', { status: 400 });
  }

  const isRefund = eventType && /refund/i.test(eventType);

  try {
    const results = [];
    for (const product of entitlements) {
      if (isRefund) {
        await revokeEntitlement(email, product);
        results.push({ product, action: 'revoked' });
      } else {
        await grantEntitlement(email, product, { orderId, event: eventType });
        results.push({ product, action: 'granted' });
      }
    }
    return new Response(JSON.stringify({ ok: true, email, results }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error('pinball-webhook store error:', err);
    return new Response(
      JSON.stringify({ error: 'store_failed', message: String(err?.message || err) }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};
