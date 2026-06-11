import { readJob, updateJob, updateIndexStatus } from './_shared/studioJobs.mjs';
import { logActivity } from './_shared/activity.mjs';

const HEYGEN_BASE = 'https://api.heygen.com';
const FAL_BASE = 'https://fal.run';
const POLL_INTERVAL_MS = 10_000;
const MAX_POLL_MS = 15 * 60 * 1000;

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function setStatus(jobId, patch) {
  await updateJob(jobId, (cur) => {
    if (!cur) return undefined;
    return { ...cur, ...patch };
  });
  if (patch.status) {
    try { await updateIndexStatus(jobId, patch.status); } catch {}
  }
}

async function finalize(jobId, patch) {
  await updateJob(jobId, (cur) => {
    if (!cur) return undefined;
    return {
      ...cur,
      ...patch,
      completedAt: new Date().toISOString(),
    };
  });
  if (patch.status) {
    try { await updateIndexStatus(jobId, patch.status); } catch {}
  }
}

// ---------- HeyGen (Avatar) ----------

async function runAvatar(job) {
  const apiKey = process.env.HEYGEN_API_KEY;
  if (!apiKey) throw new Error('HEYGEN_API_KEY not set');

  const avatarId = job.avatarId || process.env.HEYGEN_DEFAULT_AVATAR_ID || 'Daisy-inskirt-20220818';
  const voiceId = job.voiceId || process.env.HEYGEN_DEFAULT_VOICE_ID || '2d5b0e6cf36f460aa7fc47e3eee4ba54';
  const dim = job.aspect === '9_16'
    ? { width: 720, height: 1280 }
    : { width: 1280, height: 720 };

  await setStatus(job.id, {
    status: 'voiceover',
    progress: 10,
    progressLabel: 'Preparing your video…',
  });

  const videoInput = {
    character: { type: 'avatar', avatar_id: avatarId, avatar_style: 'normal' },
    voice: { type: 'text', input_text: job.script, voice_id: voiceId },
    background: { type: 'color', value: '#000000' },
  };
  if (job.captions) videoInput.caption = true;

  const genRes = await fetch(`${HEYGEN_BASE}/v2/video/generate`, {
    method: 'POST',
    headers: { 'X-Api-Key': apiKey, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_inputs: [videoInput],
      dimension: dim,
      test: false,
    }),
  });
  if (!genRes.ok) {
    const txt = await genRes.text().catch(() => '');
    throw new Error(`HeyGen generate failed: HTTP ${genRes.status} ${txt.slice(0, 300)}`);
  }
  const genData = await genRes.json().catch(() => ({}));
  const videoId = genData?.data?.video_id;
  if (!videoId) throw new Error(`HeyGen generate returned no video_id: ${JSON.stringify(genData).slice(0, 300)}`);

  await setStatus(job.id, {
    status: 'polling',
    progress: 25,
    progressLabel: 'Rendering your video…',
    heygenVideoId: videoId,
  });

  const startedAt = Date.now();
  while (Date.now() - startedAt < MAX_POLL_MS) {
    await sleep(POLL_INTERVAL_MS);
    const statusRes = await fetch(
      `${HEYGEN_BASE}/v1/video_status.get?video_id=${encodeURIComponent(videoId)}`,
      { headers: { 'X-Api-Key': apiKey } }
    );
    if (!statusRes.ok) {
      // transient — keep polling
      continue;
    }
    const statusData = await statusRes.json().catch(() => ({}));
    const s = statusData?.data?.status;
    if (s === 'completed') {
      const videoUrl = statusData?.data?.video_url;
      if (!videoUrl) throw new Error('HeyGen completed without video_url');
      await finalize(job.id, {
        status: 'complete',
        progress: 100,
        progressLabel: 'Complete',
        resultUrl: videoUrl,
      });
      return;
    }
    if (s === 'failed') {
      const err = statusData?.data?.error || 'HeyGen reported failure';
      throw new Error(`HeyGen failed: ${typeof err === 'string' ? err : JSON.stringify(err)}`);
    }
    // 'processing' / 'pending' — advance the progress bar gently.
    const elapsedFrac = Math.min(0.9, (Date.now() - startedAt) / MAX_POLL_MS);
    await setStatus(job.id, {
      progress: 25 + Math.round(elapsedFrac * 70),
      progressLabel: 'Rendering your video…',
    });
  }
  throw new Error('HeyGen polling timed out after 15 minutes');
}

// ---------- Fal (Faceless) ----------

async function falPost(path, body) {
  const apiKey = process.env.FAL_API_KEY;
  if (!apiKey) throw new Error('FAL_API_KEY not set');
  const res = await fetch(`${FAL_BASE}/${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Key ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`Fal ${path} failed: HTTP ${res.status} ${txt.slice(0, 400)}`);
  }
  return res.json();
}

async function runFaceless(job) {
  const aspect = job.aspect;
  const width = aspect === '9_16' ? 720 : 1280;
  const height = aspect === '9_16' ? 1280 : 720;

  // Normalize scenes (back-compat: build from prompts if scenes missing)
  const scenes = Array.isArray(job.scenes) && job.scenes.length
    ? job.scenes
    : (job.prompts || []).map((p) => ({ source: 'ai', prompt: p }));

  // 1) TTS
  await setStatus(job.id, {
    status: 'voiceover',
    progress: 5,
    progressLabel: 'Generating voiceover…',
  });
  const ttsRes = await falPost('fal-ai/playai/tts/v3', {
    input: job.script,
    voice: 'Jennifer (English (US)/American)',
  });
  const audioUrl = ttsRes?.audio?.url || ttsRes?.audio_url;
  if (!audioUrl) throw new Error(`TTS returned no audio url: ${JSON.stringify(ttsRes).slice(0, 300)}`);

  // 2) Build asset URL per scene (image via Flux, or use stock video URL directly)
  await setStatus(job.id, {
    status: 'visuals',
    progress: 15,
    progressLabel: `Preparing scene 1 of ${scenes.length}…`,
  });
  const imageSize = aspect === '9_16' ? 'portrait_16_9' : 'landscape_16_9';
  // assets[i] = { kind: 'image'|'video', url }
  const assets = [];
  for (let i = 0; i < scenes.length; i += 1) {
    const sc = scenes[i];
    await setStatus(job.id, {
      status: 'visuals',
      progress: 15 + Math.round((i / scenes.length) * 55),
      progressLabel: `Preparing scene ${i + 1} of ${scenes.length}…`,
    });
    if (sc.source === 'pexels' || sc.source === 'pixabay') {
      if (!sc.videoUrl) throw new Error(`Scene ${i + 1} missing stock videoUrl`);
      assets.push({ kind: 'video', url: sc.videoUrl });
    } else {
      const imgRes = await falPost('fal-ai/flux/schnell', {
        prompt: sc.prompt,
        image_size: imageSize,
        num_inference_steps: 4,
        num_images: 1,
        enable_safety_checker: true,
      });
      const url = imgRes?.images?.[0]?.url;
      if (!url) throw new Error(`Flux returned no image for scene ${i + 1}`);
      assets.push({ kind: 'image', url });
    }
  }

  // 3) Compose
  await setStatus(job.id, {
    status: 'composing',
    progress: 75,
    progressLabel: 'Composing video…',
  });

  // Estimate audio length from script length: 150 wpm.
  const words = job.script.split(/\s+/).filter(Boolean).length;
  const audioLength = Math.max(8, (words / 150) * 60);
  const sceneDuration = audioLength / assets.length;

  // The Fal ffmpeg-api/compose endpoint accepts a `video` track with keyframes of
  // either image or video URLs. Each keyframe has a duration; for videos it
  // trims/loops to fit. This is best-effort — if the compose API rejects video
  // keyframes alongside images, the fallback ffmpeg path below should still
  // surface a useful error.
  const composeBody = {
    tracks: [
      {
        id: 'video',
        type: 'video',
        keyframes: assets.map((a, idx) => ({
          url: a.url,
          timestamp: idx * sceneDuration,
          duration: sceneDuration,
        })),
      },
      {
        id: 'audio',
        type: 'audio',
        keyframes: [{ url: audioUrl, timestamp: 0, duration: audioLength }],
      },
    ],
    output: { width, height, fps: 30 },
  };

  let composeRes;
  try {
    composeRes = await falPost('fal-ai/ffmpeg-api/compose', composeBody);
  } catch (err) {
    try {
      const inputs = [...assets.map((a) => ({ url: a.url })), { url: audioUrl }];
      composeRes = await falPost('fal-ai/ffmpeg-api/ffmpeg', {
        inputs,
        command: assets
          .map((a, i) => a.kind === 'image'
            ? `-loop 1 -t ${sceneDuration.toFixed(2)} -i input${i}`
            : `-t ${sceneDuration.toFixed(2)} -i input${i}`)
          .join(' ') + ` -i input${assets.length} -filter_complex "concat=n=${assets.length}:v=1:a=0[v]" -map "[v]" -map ${assets.length}:a -shortest -s ${width}x${height} -r 30 output.mp4`,
      });
    } catch (err2) {
      throw new Error(`Fal compose failed (both compose and ffmpeg endpoints): ${err.message} | fallback: ${err2.message}`);
    }
  }

  const videoUrl =
    composeRes?.video_url ||
    composeRes?.video?.url ||
    composeRes?.output?.url ||
    composeRes?.url;
  if (!videoUrl) {
    throw new Error(`Compose returned no video url: ${JSON.stringify(composeRes).slice(0, 300)}`);
  }

  await finalize(job.id, {
    status: 'complete',
    progress: 100,
    progressLabel: 'Complete',
    resultUrl: videoUrl,
  });
}

// ---------- Entry ----------

export default async (req) => {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  let body;
  try { body = await req.json(); } catch { body = {}; }
  const jobId = body?.jobId;
  if (!jobId) return new Response('jobId required', { status: 400 });

  // ack immediately; the function continues running on the background runtime.
  // (Background functions in Netlify still expect a quick HTTP ack.)
  // We do not await the work here — we await it below, but Netlify gives us up to 15 min.

  const job = await readJob(jobId);
  if (!job) {
    return new Response('job not found', { status: 404 });
  }
  if (job.status === 'complete' || job.status === 'failed') {
    return new Response('already terminal', { status: 200 });
  }

  try {
    if (job.mode === 'avatar') {
      await runAvatar(job);
    } else if (job.mode === 'faceless') {
      await runFaceless(job);
    } else {
      throw new Error(`Unknown mode: ${job.mode}`);
    }
    const finalJob = await readJob(jobId);
    logActivity({
      type: 'studio_render',
      email: job.userEmail,
      detail: {
        jobId,
        mode: job.mode,
        aspect: job.aspect,
        captions: job.captions,
        resultUrl: finalJob?.resultUrl || null,
      },
    }).catch(() => {});
  } catch (err) {
    const message = String(err?.message || err);
    console.error(`studio-render-background ${jobId} failed:`, message);
    try {
      await finalize(jobId, {
        status: 'failed',
        error: message,
        progressLabel: 'Failed',
      });
    } catch (writeErr) {
      console.error(`failed to persist failure for ${jobId}:`, writeErr);
    }
    logActivity({
      type: 'studio_render_failed',
      email: job.userEmail,
      detail: { jobId, mode: job.mode, error: message },
    }).catch(() => {});
  }

  return new Response('ok', { status: 200 });
};
