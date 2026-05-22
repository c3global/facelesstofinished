import Anthropic from '@anthropic-ai/sdk';
import { readSession, readCookies, json } from './_shared/auth.mjs';
import { SYSTEM_PROMPT } from './_shared/systemPrompt.mjs';

const MODEL = 'claude-sonnet-4-20250514';
const MAX_TOKENS = 4000;

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

  const includeHooks = body.includeHooks !== false;
  const includeBRoll = body.includeBRoll !== false;
  const includeNotes = body.includeNotes !== false;

  let userMessage = `Generate a complete faceless YouTube video package for this topic: ${topic}`;
  if (!includeBRoll) userMessage += '\nDo not include the B-roll Shot List section.';
  if (!includeNotes) userMessage += '\nDo not include the Production Notes section.';
  if (!includeHooks) userMessage += '\nSkip the alternate hook variations section.';

  const client = new Anthropic({ apiKey });

  try {
    const response = await client.messages.create({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: userMessage }],
    });

    const text = response.content
      .filter((b) => b.type === 'text')
      .map((b) => b.text)
      .join('\n');

    return json({ text });
  } catch (err) {
    console.error('Anthropic error:', err);
    return json({ error: 'generation_failed', message: String(err?.message || err) }, { status: 502 });
  }
};
