export async function generateScript({ topic, includeHooks, includeBRoll, includeNotes }) {
  const res = await fetch('/api/generate-script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ topic, includeHooks, includeBRoll, includeNotes }),
  });

  if (res.status === 401) {
    const err = new Error('unauthorized');
    err.code = 'unauthorized';
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
  const data = await res.json();
  return data.text;
}

export async function fetchSession() {
  const res = await fetch('/api/auth-me', { credentials: 'include' });
  if (!res.ok) return null;
  const data = await res.json();
  return data.authenticated ? { email: data.email } : null;
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
  return res.json();
}

export async function logout() {
  await fetch('/api/auth-logout', { method: 'POST', credentials: 'include' });
}
