import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement } from './_shared/store.mjs';

async function searchPexels({ query, orientation, perPage }) {
  const apiKey = process.env.PEXELS_API_KEY;
  if (!apiKey) throw new Error('PEXELS_API_KEY not set');
  const params = new URLSearchParams({
    query,
    per_page: String(perPage),
    orientation: orientation === 'portrait' ? 'portrait' : 'landscape',
  });
  const res = await fetch(`https://api.pexels.com/videos/search?${params}`, {
    headers: { Authorization: apiKey },
  });
  if (!res.ok) throw new Error(`Pexels HTTP ${res.status}`);
  const data = await res.json().catch(() => ({}));
  const videos = Array.isArray(data?.videos) ? data.videos : [];
  return videos.map((v) => {
    // Pick the smallest HD file under 720p height; fallback to smallest .mp4
    const files = Array.isArray(v.video_files) ? v.video_files : [];
    const mp4s = files.filter((f) => (f.link || '').includes('.mp4') || f.file_type === 'video/mp4');
    const under720 = mp4s.filter((f) => (f.height || 0) > 0 && (f.height || 0) <= 720);
    const sorted = (under720.length ? under720 : mp4s).slice().sort(
      (a, b) => (a.height || 0) - (b.height || 0)
    );
    const pick = sorted[sorted.length - 1] || sorted[0] || files[0] || {};
    return {
      id: String(v.id),
      sourceId: 'pexels',
      previewImageUrl: v.image || '',
      durationSec: v.duration || 0,
      videoUrl: pick.link || '',
      sourceName: 'Pexels',
    };
  }).filter((r) => r.videoUrl);
}

async function searchPixabay({ query, orientation, perPage }) {
  const apiKey = process.env.PIXABAY_API_KEY;
  if (!apiKey) throw new Error('PIXABAY_API_KEY not set');
  const params = new URLSearchParams({
    key: apiKey,
    q: query,
    per_page: String(perPage),
  });
  // Pixabay video orientation is filtered server-side via `video_type` only; orientation
  // isn't a direct parameter, so we filter client-side.
  const res = await fetch(`https://pixabay.com/api/videos/?${params}`);
  if (!res.ok) throw new Error(`Pixabay HTTP ${res.status}`);
  const data = await res.json().catch(() => ({}));
  const hits = Array.isArray(data?.hits) ? data.hits : [];
  const mapped = hits.map((h) => {
    const videos = h.videos || {};
    // Prefer medium then small then large
    const pick = videos.medium || videos.small || videos.tiny || videos.large || {};
    // Thumbnail: pixabay returns a `thumbnail` field per video size in newer API responses
    const thumb = pick.thumbnail
      || (h.picture_id ? `https://i.vimeocdn.com/video/${h.picture_id}_295x166.jpg` : '')
      || (videos.large && videos.large.thumbnail) || '';
    return {
      id: String(h.id),
      sourceId: 'pixabay',
      previewImageUrl: thumb,
      durationSec: h.duration || 0,
      videoUrl: pick.url || '',
      sourceName: 'Pixabay',
      _width: pick.width || 0,
      _height: pick.height || 0,
    };
  }).filter((r) => r.videoUrl);
  // Light orientation filter
  const filtered = orientation === 'portrait'
    ? mapped.filter((m) => m._height >= m._width)
    : mapped.filter((m) => m._width >= m._height);
  const out = (filtered.length ? filtered : mapped).map(({ _width, _height, ...rest }) => rest);
  return out;
}

export default async (req) => {
  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });
  const allowed = await hasEntitlement(session.email, 'studio').catch(() => false);
  if (!allowed) return json({ error: 'entitlement_required', entitlement: 'studio' }, { status: 403 });

  const url = new URL(req.url);
  const source = String(url.searchParams.get('source') || '').toLowerCase();
  const query = String(url.searchParams.get('query') || '').trim();
  const orientation = String(url.searchParams.get('orientation') || 'portrait').toLowerCase();
  const perPage = Math.min(20, Math.max(1, parseInt(url.searchParams.get('perPage') || '10', 10) || 10));

  if (!query) return json({ results: [], error: 'query required' });
  if (source !== 'pexels' && source !== 'pixabay') {
    return json({ results: [], error: 'invalid source' });
  }

  try {
    const results = source === 'pexels'
      ? await searchPexels({ query, orientation, perPage })
      : await searchPixabay({ query, orientation, perPage });
    return json({ results });
  } catch (err) {
    return json({ results: [], error: String(err?.message || err).slice(0, 200) });
  }
};
