import Anthropic from '@anthropic-ai/sdk';
import { readSession, getCookieHeader } from './_shared/auth.mjs';
import { SYSTEM_PROMPT } from './_shared/systemPrompt.mjs';

const MODEL = 'claude-sonnet-4-20250514';
const MAX_TOKENS = 4000;

export const handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }

  const session = readSession(getCookieHeader(event));
  if (!session) {
    return {
      statusCode: 401,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'unauthorized' }),
    };
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'server_misconfigured' }),
    };
  }

  let body;
  try {
    body = JSON.parse(event.body || '{}');
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: 'invalid_json' }) };
  }

  const topic = String(body.topic || '').trim();
  if (!topic) {
    return { statusCode: 400, body: JSON.stringify({ error: 'topic_required' }) };
  }

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

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    };
  } catch (err) {
    console.error('Anthropic error:', err);
    return {
      statusCode: 502,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'generation_failed' }),
    };
  }
};
