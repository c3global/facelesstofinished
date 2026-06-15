import Anthropic from '@anthropic-ai/sdk';
import { readJob, updateJob } from './_shared/scriptJobs.mjs';
import { buildSystemPrompt, buildShortsSystemPrompt } from './_shared/systemPrompt.mjs';
import { recordScriptGeneration, recordShortsGeneration } from './_shared/store.mjs';

const MODEL = 'claude-sonnet-4-6';
const FLUSH_INTERVAL_MS = 600;

export default async (req) => {
  let jobId;
  try {
    const body = await req.json();
    jobId = body?.jobId;
  } catch {
    return new Response('invalid_json', { status: 400 });
  }
  if (!jobId) return new Response('jobId_required', { status: 400 });

  const job = await readJob(jobId);
  if (!job) return new Response('job_not_found', { status: 404 });
  if (job.status !== 'queued') {
    return new Response('already_processed', { status: 200 });
  }

  await updateJob(jobId, (j) =>
    j ? { ...j, status: 'streaming', updatedAt: new Date().toISOString() } : undefined
  );

  let systemPrompt;
  let userMessage;
  let maxTokens;

  if (job.mode === 'shorts') {
    systemPrompt = buildShortsSystemPrompt({ platform: job.platform || 'youtube' });
    userMessage = `Generate a complete faceless short-form video package for this topic: ${job.topic}`;
    if (job.angle) {
      userMessage += `\n\nHOOK ANGLE BIAS FOR THIS SHORT: ${job.angle}. Every other short in this batch is using a different angle, so commit fully to this one — don't hedge.`;
    }
    maxTokens = 3500;
  } else {
    let msg = `Generate a complete faceless YouTube video package for this topic: ${job.topic}`;
    if (job.includeBRoll === false) {
      msg +=
        '\nDo not include the consolidated B-roll Shot List section. Inline cues inside the narration are still required.';
    }
    if (job.includeNotes === false) msg += '\nDo not include the Production Notes section.';
    if (job.includeHooks === false) msg += '\nSkip the alternate hook variations section.';
    userMessage = msg;
    systemPrompt = buildSystemPrompt({ length: job.length || 'medium' });
    maxTokens = 8192;
  }

  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

  let accumulated = '';
  let lastFlushAt = Date.now();

  async function flush() {
    const snapshot = accumulated;
    await updateJob(jobId, (j) => {
      if (!j) return undefined;
      if (j.status === 'complete' || j.status === 'failed') return undefined;
      return { ...j, text: snapshot, updatedAt: new Date().toISOString() };
    }).catch((err) => console.error('flush update failed:', err));
    lastFlushAt = Date.now();
  }

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
        accumulated += event.delta.text;
        if (Date.now() - lastFlushAt >= FLUSH_INTERVAL_MS) {
          await flush();
        }
      }
    }

    await updateJob(jobId, (j) => {
      if (!j) return undefined;
      return {
        ...j,
        text: accumulated,
        status: 'complete',
        completedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
    });

    const tracker = job.mode === 'shorts' ? recordShortsGeneration : recordScriptGeneration;
    tracker(job.userEmail).catch((err) => console.error('record generation error:', err));
  } catch (err) {
    console.error('Anthropic stream error:', err);
    await updateJob(jobId, (j) => {
      if (!j) return undefined;
      return {
        ...j,
        text: accumulated,
        status: 'failed',
        error: String(err?.message || err).slice(0, 500),
        completedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
    }).catch(() => {});
  }

  return new Response('done', { status: 200 });
};
