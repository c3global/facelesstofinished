import { isAdmin } from './_shared/admin.mjs';
import { json, readSession, readCookies } from './_shared/auth.mjs';
import {
  listActivity,
  getActivityRaw,
  getWebhookPayload,
  logActivity,
  ACTIVITY_TYPES,
} from './_shared/activity.mjs';
import { processWebhook } from './pinball-webhook.mjs';

export default async (req) => {
  if (!isAdmin(req)) return json({ error: 'unauthorized' }, { status: 401 });

  const url = new URL(req.url);
  const action = url.searchParams.get('action');
  const sessionEmail = (() => {
    try { return readSession(readCookies(req))?.email || null; } catch { return null; }
  })();

  if (req.method === 'GET') {
    const limitRaw = parseInt(url.searchParams.get('limit') || '100', 10);
    const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(1, limitRaw), 500) : 100;
    const typeParam = url.searchParams.get('type');
    const type = typeParam && ACTIVITY_TYPES.includes(typeParam) ? typeParam : undefined;
    const activity = await listActivity({ limit, type });
    return json({ activity });
  }

  if (req.method === 'POST' && action === 'replay') {
    let body = {};
    try {
      body = await req.json();
    } catch {
      return json({ error: 'invalid_json' }, { status: 400 });
    }
    const activityId = String(body.activityId || '').trim();
    if (!activityId) return json({ error: 'missing_activity_id' }, { status: 400 });

    // Find the original activity record so we can pull email/event for logging.
    const all = await getActivityRaw();
    const original = all.find((e) => e.id === activityId) || null;

    const stored = await getWebhookPayload(activityId);
    if (!stored || !stored.payload) {
      return json({ error: 'payload_not_found', activityId }, { status: 404 });
    }

    const meta = stored.meta || {};
    const result = await processWebhook(stored.payload, {
      event: meta.event || original?.detail?.event || null,
      productParam: 'base',
      extraMeta: { replay: true, originalId: activityId, replayedBy: sessionEmail },
    });

    return json(
      {
        ok: result.ok,
        status: result.status,
        body: result.body,
        replayedBy: sessionEmail,
        originalId: activityId,
      },
      { status: result.ok ? 200 : result.status }
    );
  }

  return new Response('Method not allowed', { status: 405 });
};
