import { getStore } from '@netlify/blobs';
import { readSession, readCookies, json } from './_shared/auth.mjs';
import { hasEntitlement } from './_shared/store.mjs';

const CACHE_STORE = 'f48-heygen-cache';
const CACHE_KEY = 'avatars-v1';
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

async function fetchFromHeyGen() {
  const apiKey = process.env.HEYGEN_API_KEY;
  if (!apiKey) throw new Error('HEYGEN_API_KEY not set');
  const res = await fetch('https://api.heygen.com/v2/avatars', {
    headers: { 'X-Api-Key': apiKey },
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`HeyGen avatars failed: HTTP ${res.status} ${txt.slice(0, 200)}`);
  }
  const data = await res.json().catch(() => ({}));
  const list = data?.data?.avatars || [];
  return list.map((a) => ({
    id: a.avatar_id,
    name: a.avatar_name,
    gender: a.gender || '',
    previewImageUrl: a.preview_image_url || '',
    previewVideoUrl: a.preview_video_url || '',
  }));
}

export default async (req) => {
  const session = readSession(readCookies(req));
  if (!session) return json({ error: 'unauthorized' }, { status: 401 });
  const allowed = await hasEntitlement(session.email, 'studio').catch(() => false);
  if (!allowed) return json({ error: 'entitlement_required', entitlement: 'studio' }, { status: 403 });

  try {
    const store = getStore(CACHE_STORE);
    const cached = await store.get(CACHE_KEY, { type: 'json' }).catch(() => null);
    if (cached && cached.fetchedAt && Date.now() - cached.fetchedAt < CACHE_TTL_MS && Array.isArray(cached.data)) {
      return json({ avatars: cached.data });
    }
    const avatars = await fetchFromHeyGen();
    await store.setJSON(CACHE_KEY, { data: avatars, fetchedAt: Date.now() }).catch(() => {});
    return json({ avatars });
  } catch (err) {
    return json({ error: String(err?.message || err), avatars: [] }, { status: 500 });
  }
};
