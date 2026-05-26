export async function generateScript({
  mode = 'long',
  topic,
  length,
  platform,
  angle,
  includeHooks,
  includeBRoll,
  includeNotes,
  onChunk,
}) {
  const res = await fetch('/api/generate-script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ mode, topic, length, platform, angle, includeHooks, includeBRoll, includeNotes }),
  });

  if (res.status === 401) {
    const err = new Error('unauthorized');
    err.code = 'unauthorized';
    throw err;
  }
  if (res.status === 403) {
    let detail = null;
    try { detail = await res.json(); } catch {}
    const err = new Error('entitlement_required');
    err.code = 'entitlement_required';
    err.entitlement = detail?.entitlement || null;
    throw err;
  }
  if (!res.ok) {
    let detail = '';
    try { detail = JSON.stringify(await res.json()); } catch { detail = await res.text().catch(() => ''); }
    const err = new Error(`generate_failed_${res.status}`);
    err.code = 'generate_failed';
    err.detail = `HTTP ${res.status} ${detail}`;
    throw err;
  }

  if (!res.body) {
    const text = await res.text();
    return text;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let text = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    text += chunk;
    if (onChunk) onChunk(chunk, text);
  }
  text += decoder.decode();
  return text;
}

export async function repurposeAsShort({ sourceScript, platform, angle, onChunk }) {
  const res = await fetch('/api/generate-shorts-from-script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ sourceScript, platform, angle }),
  });

  if (res.status === 401) {
    const err = new Error('unauthorized');
    err.code = 'unauthorized';
    throw err;
  }
  if (res.status === 403) {
    let detail = null;
    try { detail = await res.json(); } catch {}
    const err = new Error('entitlement_required');
    err.code = 'entitlement_required';
    err.entitlement = detail?.entitlement || null;
    throw err;
  }
  if (!res.ok) {
    let detail = '';
    try { detail = JSON.stringify(await res.json()); } catch { detail = await res.text().catch(() => ''); }
    const err = new Error(`repurpose_failed_${res.status}`);
    err.code = 'repurpose_failed';
    err.detail = `HTTP ${res.status} ${detail}`;
    throw err;
  }

  if (!res.body) return await res.text();
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let text = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    text += chunk;
    if (onChunk) onChunk(chunk, text);
  }
  text += decoder.decode();
  return text;
}

export async function fetchSession() {
  const res = await fetch('/api/auth-me', { credentials: 'include' });
  if (!res.ok) return null;
  const data = await res.json();
  return data.authenticated
    ? { email: data.email, entitlements: data.entitlements || [] }
    : null;
}

export async function loginWithEmail(email) {
  const res = await fetch('/api/auth-login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email }),
  });
  if (res.status === 403) {
    const err = new Error('not_a_buyer');
    err.code = 'not_a_buyer';
    throw err;
  }
  if (res.status === 400) {
    const err = new Error('invalid_email');
    err.code = 'invalid_email';
    throw err;
  }
  if (!res.ok) {
    let detail = '';
    try { detail = JSON.stringify(await res.json()); } catch { detail = await res.text().catch(() => ''); }
    const err = new Error(`login_failed_${res.status}`);
    err.code = 'login_failed';
    err.detail = `HTTP ${res.status} ${detail}`;
    throw err;
  }
  const data = await res.json();
  return { email: data.email, entitlements: data.entitlements || [] };
}

export async function logout() {
  await fetch('/api/auth-logout', { method: 'POST', credentials: 'include' });
}
