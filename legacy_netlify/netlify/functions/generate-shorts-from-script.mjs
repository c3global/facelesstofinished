import Anthropic from '@anthropic-ai/sdk';
import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement, recordShortsGeneration } from './_shared/store.mjs';
import { buildShortsSystemPrompt } from './_shared/systemPrompt.mjs';

const MODEL = 'claude-sonnet-4-20250514';
const VALID_PLATFORMS = new Set(['youtube', 'reels', 'tiktok']);

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return json({ error: 'server_misconfigured' }, { status: 500 });

  const allowed = await hasEntitlement(session.email, 'shorts').catch(() => false);
  if (!allowed) {
    return json({ error: 'entitlement_required', entitlement: 'shorts' }, { status: 403 });
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: 'invalid_json' }, { status: 400 });
  }

  const sourceScript = String(body.sourceScript || '').trim();
  if (!sourceScript) return json({ error: 'source_required' }, { status: 400 });
  if (sourceScript.length > 30000) return json({ error: 'source_too_large' }, { status: 400 });

  const platform = VALID_PLATFORMS.has(body.platform) ? body.platform : 'youtube';
  const angle = typeof body.angle === 'string' && body.angle.trim() ? body.angle.trim().slice(0, 40) : 'curiosity';

  const base = buildShortsSystemPrompt({ platform });
  const systemPrompt = `${base}

REPURPOSE MODE: You are not generating a short from scratch. You are deriving a short from an EXISTING long-form video script the same creator already wrote. Stay faithful to that script's voice, facts, examples, and B-roll vocabulary. Pull one specific idea, story, or contrarian beat out of the long-form and turn it into a self-contained short. Do NOT just summarize the whole video.`;

  const userMessage = `Here is the long-form script (sections separated by ### headers):

---SOURCE SCRIPT---
${sourceScript}
---END SOURCE SCRIPT---

Derive ONE faceless short from this source, biased toward the angle: "${angle}". Pick a single idea or beat from the source that fits that angle and turn it into a complete short package using the exact output structure defined in your system instructions.`;

  const client = new Anthropic({ apiKey });
  const encoder = new TextEncoder();
  const readable = new ReadableStream({
    async start(controller) {
      try {
        const stream = client.messages.stream({
          model: MODEL,
          max_tokens: 3500,
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
        recordShortsGeneration(session.email).catch((err) =>
          console.error('record generation error:', err)
        );
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
