import crypto from 'node:crypto';
import { grantEntitlement, revokeEntitlement, KNOWN_ENTITLEMENTS } from './_shared/store.mjs';
import { logActivity, storeWebhookPayload } from './_shared/activity.mjs';

// Map GHL/Pinball product IDs → app entitlements. Add a row here when you create a new product.
// Bumps and bonuses (Topic Vault, etc.) intentionally omitted — they're delivered separately, not as app entitlements.
const PRODUCT_ID_TO_ENTITLEMENT = {
  '01ks3pmetahzgx2mfg7q5crs0j': 'base',   // Faceless to Finished in 48
  '01ksgx97wad7vcc27ycvw0erg7': 'shorts', // Faceless Shorts (OTO + backend)
  '01kv67kgk9z028tn0hy1kzk92r': 'studio', // Studio Founder Lifetime
};

// Higher tiers imply lower tiers — Studio is the top of the stack and grants
// access to everything below it. Applied on grant only, not on refund (refunds
// revoke only the specific entitlement they target, since the buyer may have
// purchased the lower tiers separately).
const TIER_IMPLIES = {
  studio: ['shorts', 'base'],
  shorts: ['base'],
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

// Extracts the order total in cents. Handles common shapes: integer cents,
// decimal dollar strings, or floats. Returns null when nothing usable.
function extractOrderTotalCents(p) {
  const raw =
    p?.data?.order?.total_amount ??
    p?.order?.total_amount ??
    p?.data?.total_amount ??
    p?.total_amount ??
    null;
  if (raw == null) return null;
  const num = typeof raw === 'string' ? Number(raw) : raw;
  if (!Number.isFinite(num) || num <= 0) return null;
  // Heuristic: integers >= 100 look like cents; small/decimal values look like dollars.
  if (Number.isInteger(num) && num >= 100) return num;
  return Math.round(num * 100);
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

function summarizePayload(payload) {
  try {
    const s = JSON.stringify(payload);
    return s.length > 500 ? `${s.slice(0, 500)}…[truncated]` : s;
  } catch {
    return '[unserializable]';
  }
}

// Core handler — extracted so the admin replay endpoint can invoke it without
// going through HTTP. Pass `extraMeta` to tag the replay in activity entries.
export async function processWebhook(payload, { event: forcedEvent, productParam = 'base', extraMeta = {} } = {}) {
  const eventType = forcedEvent || payload?.event || payload?.type || null;
  const email = extractEmail(payload);
  const orderId = extractOrderId(payload);
  const orderTotalCents = extractOrderTotalCents(payload);
  const isRefund = eventType && /refund/i.test(eventType);
  let entitlements = resolveEntitlements(payload, productParam);

  // On grants, cascade higher tiers into the lower ones they imply, so a Studio
  // buyer is never locked out of the Script Engine they paid for.
  if (!isRefund) {
    const expanded = new Set(entitlements);
    for (const tier of entitlements) {
      const implied = TIER_IMPLIES[tier];
      if (implied) implied.forEach((e) => expanded.add(e));
    }
    entitlements = [...expanded];
  }

  if (!email) {
    await logActivity({
      type: 'webhook_failed',
      email: null,
      detail: {
        reason: 'no_email_in_payload',
        payloadSummary: summarizePayload(payload),
        httpStatus: 400,
        ...extraMeta,
      },
    });
    return { ok: false, status: 400, body: 'No email in payload' };
  }

  try {
    const results = [];
    for (const product of entitlements) {
      if (isRefund) {
        await revokeEntitlement(email, product);
        results.push({ product, action: 'revoked' });
      } else {
        await grantEntitlement(email, product, { orderId, orderTotalCents, event: eventType });
        results.push({ product, action: 'granted' });
      }
    }
    const activity = await logActivity({
      type: 'webhook',
      email,
      detail: {
        event: eventType,
        orderId,
        products: results.map((r) => r.product),
        actions: results,
        ...extraMeta,
      },
    });
    // Stash raw payload for future replay (keyed by activity id).
    if (activity?.id) {
      await storeWebhookPayload(activity.id, payload, { event: eventType, email, orderId });
    }
    return { ok: true, status: 200, body: { ok: true, email, results, activityId: activity?.id || null } };
  } catch (err) {
    console.error('pinball-webhook store error:', err);
    await logActivity({
      type: 'webhook_failed',
      email,
      detail: {
        reason: 'store_failed',
        error: String(err?.message || err),
        payloadSummary: summarizePayload(payload),
        httpStatus: 500,
        ...extraMeta,
      },
    });
    return {
      ok: false,
      status: 500,
      body: { error: 'store_failed', message: String(err?.message || err) },
    };
  }
}

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  if (!verifyToken(req)) {
    await logActivity({
      type: 'webhook_failed',
      email: null,
      detail: { reason: 'invalid_token', httpStatus: 401 },
    });
    return new Response('Invalid or missing token', { status: 401 });
  }

  let payload;
  try {
    payload = await req.json();
  } catch {
    await logActivity({
      type: 'webhook_failed',
      email: null,
      detail: { reason: 'invalid_json', httpStatus: 400 },
    });
    return new Response('Invalid JSON', { status: 400 });
  }

  const eventType = extractEvent(payload, req);
  const productParam = new URL(req.url).searchParams.get('product') || 'base';
  const result = await processWebhook(payload, { event: eventType, productParam });

  if (result.ok) {
    return new Response(JSON.stringify(result.body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }
  if (typeof result.body === 'string') {
    return new Response(result.body, { status: result.status });
  }
  return new Response(JSON.stringify(result.body), {
    status: result.status,
    headers: { 'Content-Type': 'application/json' },
  });
};
