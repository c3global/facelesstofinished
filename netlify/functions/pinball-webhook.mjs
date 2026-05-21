import crypto from 'node:crypto';
import { addBuyer, removeBuyer } from './_shared/store.mjs';

function extractToken(event) {
  const params = new URLSearchParams(event.rawQuery || '');
  return params.get('token') || event.queryStringParameters?.token || null;
}

function verifyToken(event) {
  const expected = process.env.PINBALL_WEBHOOK_TOKEN;
  if (!expected) return false;
  const provided = extractToken(event);
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

  if (!verifyToken(event)) {
    return { statusCode: 401, body: 'Invalid or missing token' };
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
