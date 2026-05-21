import Anthropic from '@anthropic-ai/sdk';
import { SYSTEM_PROMPT } from './systemPrompt.js';

const MODEL = 'claude-sonnet-4-20250514';
const MAX_TOKENS = 2000;

export async function generateScript({ topic, includeHooks, includeBRoll, includeNotes }) {
  const apiKey = import.meta.env.VITE_ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error('Missing VITE_ANTHROPIC_API_KEY');
  }

  let userMessage = `Generate a complete faceless YouTube video script for this topic: ${topic}`;
  if (!includeBRoll) userMessage += '\nDo not include the B-roll Shot List section.';
  if (!includeNotes) userMessage += '\nDo not include the Production Notes section.';
  if (!includeHooks) userMessage += '\nSkip alternate hook variations.';

  const client = new Anthropic({
    apiKey,
    dangerouslyAllowBrowser: true,
  });

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

  return text;
}
