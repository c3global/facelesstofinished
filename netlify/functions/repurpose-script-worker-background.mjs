import Anthropic from '@anthropic-ai/sdk';
import { readJob, updateJob } from './_shared/scriptJobs.mjs';
import { buildShortsSystemPrompt } from './_shared/systemPrompt.mjs';
import { recordShortsGeneration } from './_shared/store.mjs';

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
  if (job.kind !== 'repurpose') return new Response('wrong_kind', { status: 400 });
  if (job.status !== 'queued') {
    return new Response('already_processed', { status: 200 });
  }

  await updateJob(jobId, (j) =>
    j ? { ...j, status: 'streaming', updatedAt: new Date().toISOString() } : undefined
  );

  const base = buildShortsSystemPrompt({ platform: job.platform || 'youtube' });
  const systemPrompt = `${base}

REPURPOSE MODE: You are not generating a short from scratch. You are deriving a short from an EXISTING long-form video script the same creator already wrote. Stay faithful to that script's voice, facts, examples, and B-roll vocabulary. Pull one specific idea, story, or contrarian beat out of the long-form and turn it into a self-contained short. Do NOT just summarize the whole video.`;

  const userMessage = `Here is the long-form script (sections separated by ### headers):

---SOURCE SCRIPT---
${job.sourceScript}
---END SOURCE SCRIPT---

Derive ONE faceless short from this source, biased toward the angle: "${job.angle || 'curiosity'}". Pick a single idea or beat from the source that fits that angle and turn it into a complete short package using the exact output structure defined in your system instructions.`;

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

    recordShortsGeneration(job.userEmail).catch((err) =>
      console.error('record generation error:', err)
    );
  } catch (err) {
    console.error('Anthropic repurpose stream error:', err);
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
