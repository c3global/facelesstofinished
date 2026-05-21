import crypto from 'node:crypto';
import { addBuyer, removeBuyer } from './_shared/store.mjs';

function extractSignature(event) {
  const h = event.headers || {};
  return (
    h['x-pinball-signature'] ||
    h['pinball-signature'] ||
    h['x-webhook-signature'] ||
    h['x-signature'] ||
    null
  );
}

function verifySignature(rawBody, signature) {
  const secret = process.env.PINBALL_WEBHOOK_SECRET;
  if (!secret) {
    // If no secret is configured, refuse the webhook rather than accept blindly.
    return false;
  }
  if (!signature) return false;
  const expected = crypto.createHmac('sha256', secret).update(rawBody).digest('hex');
  const provided = signature.startsWith('sha256=') ? signature.slice(7) : signature;
  try {
    return crypto.timingSafeEqual(
      Buffer.from(expected, 'hex'),
      Buffer.from(provided, 'hex')
    );
  } catch {
    return false;
  }
}

function extractEmail(payload) {
  return (
    payload?.customer?.email ||
    payload?.data?.customer?.email ||
    payload?.data?.email ||
    payload?.order?.customer?.email ||
    payload?.data?.order?.customer?.email ||
    payload?.email ||
    null
  );
}

function extractOrderId(payload) {
  return (
    payload?.order?.id ||
    payload?.data?.order?.id ||
    payload?.order_id ||
    payload?.data?.order_id ||
    payload?.id ||
    payload?.data?.id ||
    null
  );
}

function extractEvent(payload, event) {
  return (
    payload?.event ||
    payload?.type ||
    event.headers?.['x-pinball-event'] ||
    event.headers?.['x-event-type'] ||
    null
  );
}

export const handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }

  const rawBody = event.body || '';
  const signature = extractSignature(event);

  if (!verifySignature(rawBody, signature)) {
    return { statusCode: 401, body: 'Invalid signature' };
  }

  let payload;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return { statusCode: 400, body: 'Invalid JSON' };
  }

  const eventType = extractEvent(payload, event);
  const email = extractEmail(payload);
  const orderId = extractOrderId(payload);

  if (!email) {
    return { statusCode: 400, body: 'No email in payload' };
  }

  if (eventType && /refund/i.test(eventType)) {
    await removeBuyer(email);
    return { statusCode: 200, body: JSON.stringify({ ok: true, action: 'removed', email }) };
  }

  await addBuyer(email, { orderId, event: eventType });
  return { statusCode: 200, body: JSON.stringify({ ok: true, action: 'added', email }) };
};
