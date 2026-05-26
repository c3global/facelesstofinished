import crypto from 'node:crypto';
import { grantEntitlement, revokeEntitlement, KNOWN_ENTITLEMENTS } from './_shared/store.mjs';

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
  const product = KNOWN_ENTITLEMENTS.includes(productParam) ? productParam : 'base';

  if (!email) {
    console.error('pinball-webhook: no email in payload', JSON.stringify(payload).slice(0, 500));
    return new Response('No email in payload', { status: 400 });
  }

  try {
    if (eventType && /refund/i.test(eventType)) {
      await revokeEntitlement(email, product);
      return new Response(JSON.stringify({ ok: true, action: 'revoked', email, product }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    await grantEntitlement(email, product, { orderId, event: eventType });
    return new Response(JSON.stringify({ ok: true, action: 'granted', email, product }), {
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
