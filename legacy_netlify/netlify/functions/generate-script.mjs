import Anthropic from '@anthropic-ai/sdk';
import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement, recordScriptGeneration, recordShortsGeneration } from './_shared/store.mjs';
import { buildSystemPrompt, buildShortsSystemPrompt } from './_shared/systemPrompt.mjs';

const MODEL = 'claude-sonnet-4-20250514';
const VALID_LENGTHS = new Set(['short', 'medium', 'long']);
const VALID_PLATFORMS = new Set(['youtube', 'reels', 'tiktok']);

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return json({ error: 'server_misconfigured' }, { status: 500 });

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }

  const topic = String(body.topic || '').trim();
  if (!topic) return json({ error: 'topic_required' }, { status: 400 });

  const mode = body.mode === 'shorts' ? 'shorts' : 'long';
  const requiredEntitlement = mode === 'shorts' ? 'shorts' : 'base';

  const allowed = await hasEntitlement(session.email, requiredEntitlement).catch(() => false);
  if (!allowed) {
    return json(
      { error: 'entitlement_required', entitlement: requiredEntitlement },
      { status: 403 }
    );
  }

  let systemPrompt;
  let userMessage;
  let maxTokens;

  if (mode === 'shorts') {
    const platform = VALID_PLATFORMS.has(body.platform) ? body.platform : 'youtube';
    const angle = typeof body.angle === 'string' && body.angle.trim() ? body.angle.trim().slice(0, 40) : null;
    systemPrompt = buildShortsSystemPrompt({ platform });
    userMessage = `Generate a complete faceless short-form video package for this topic: ${topic}`;
    if (angle) {
      userMessage += `\n\nHOOK ANGLE BIAS FOR THIS SHORT: ${angle}. Every other short in this batch is using a different angle, so commit fully to this one — don't hedge.`;
    }
    maxTokens = 3500;
  } else {
    const includeHooks = body.includeHooks !== false;
    const includeBRoll = body.includeBRoll !== false;
    const includeNotes = body.includeNotes !== false;
    const length = VALID_LENGTHS.has(body.length) ? body.length : 'medium';

    let msg = `Generate a complete faceless YouTube video package for this topic: ${topic}`;
    if (!includeBRoll) msg += '\nDo not include the consolidated B-roll Shot List section. Inline cues inside the narration are still required.';
    if (!includeNotes) msg += '\nDo not include the Production Notes section.';
    if (!includeHooks) msg += '\nSkip the alternate hook variations section.';
    userMessage = msg;
    systemPrompt = buildSystemPrompt({ length });
    maxTokens = 8192;
  }

  const client = new Anthropic({ apiKey });

  const encoder = new TextEncoder();
  const readable = new ReadableStream({
    async start(controller) {
      try {
        const stream = client.messages.stream({
          model: MODEL,
          max_tokens: maxTokens,
          system: systemPrompt,
          messages: [{ role: 'user', content: userMessage }],
        });

        for await (const event of stream) {
          if (
            event.type === 'content_block_delta' &&
            event.delta?.type === 'text_delta' &&
            event.delta.text
          ) {
            controller.enqueue(encoder.encode(event.delta.text));
          }
        }
        // Track generation only on successful completion of the stream.
        const tracker = mode === 'shorts' ? recordShortsGeneration : recordScriptGeneration;
        tracker(session.email).catch((err) => console.error('record generation error:', err));
        controller.close();
      } catch (err) {
        console.error('Anthropic stream error:', err);
        try {
          controller.enqueue(encoder.encode(`\n\n[STREAM_ERROR] ${String(err?.message || err)}`));
        } catch {}
        controller.close();
      }
    },
  });

  return new Response(readable, {
    status: 200,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Accel-Buffering': 'no',
    },
  });
};
