import React, { useEffect, useState } from 'react';

const TOKEN_KEY = 'f48_admin_token';

export default function Admin() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || '');
  const [authed, setAuthed] = useState(false);
  const [list, setList] = useState([]);
  const [knownEnts, setKnownEnts] = useState(['base', 'shorts']);
  const [newEmail, setNewEmail] = useState('');
  const [newEnts, setNewEnts] = useState({ base: true, shorts: false });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const headers = { 'X-Admin-Token': token, 'Content-Type': 'application/json' };

  const refresh = async () => {
    setError('');
    const res = await fetch('/api/admin-buyers', { headers });
    if (res.status === 401) {
      setAuthed(false);
      setError('Invalid admin token.');
      localStorage.removeItem(TOKEN_KEY);
      return;
    }
    if (!res.ok) {
      let detail = '';
      try { detail = JSON.stringify(await res.json()); } catch { detail = await res.text().catch(() => ''); }
      setError(`Failed to load (HTTP ${res.status}). ${detail}`);
      return;
    }
    const data = await res.json();
    setList(data.buyers || []);
    if (Array.isArray(data.knownEntitlements) && data.knownEntitlements.length) {
      setKnownEnts(data.knownEntitlements);
    }
    setAuthed(true);
    localStorage.setItem(TOKEN_KEY, token);
  };

  useEffect(() => {
    if (token) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = async (e) => {
    e?.preventDefault();
    if (!newEmail.trim()) return;
    const entitlements = Object.entries(newEnts).filter(([, v]) => v).map(([k]) => k);
    if (entitlements.length === 0) {
      setError('Pick at least one entitlement.');
      return;
    }
    setBusy(true);
    setError('');
    const res = await fetch('/api/admin-buyers', {
      method: 'POST',
      headers,
      body: JSON.stringify({ email: newEmail.trim(), entitlements }),
    });
    setBusy(false);
    if (!res.ok) {
      setError('Failed to add.');
      return;
    }
    setNewEmail('');
    setNewEnts({ base: true, shorts: false });
    refresh();
  };

  const grant = async (email, entitlement) => {
    setBusy(true);
    await fetch('/api/admin-buyers?action=grant', {
      method: 'POST',
      headers,
      body: JSON.stringify({ email, entitlement }),
    });
    setBusy(false);
    refresh();
  };

  const revoke = async (email, entitlement) => {
    if (!confirm(`Revoke "${entitlement}" from ${email}?`)) return;
    setBusy(true);
    await fetch('/api/admin-buyers?action=revoke', {
      method: 'POST',
      headers,
      body: JSON.stringify({ email, entitlement }),
    });
    setBusy(false);
    refresh();
  };

  const remove = async (email) => {
    if (!confirm(`Remove ${email} entirely?`)) return;
    setBusy(true);
    await fetch('/api/admin-buyers', {
      method: 'DELETE',
      headers,
      body: JSON.stringify({ email }),
    });
    setBusy(false);
    refresh();
  };

  if (!authed) {
    return (
      <div className="page">
        <main className="main">
          <section className="login-card">
            <h2 className="hero-headline">Admin</h2>
            <p className="hero-sub">Enter your admin token to manage the buyer list.</p>
            <form
              className="login-form"
              onSubmit={(e) => {
                e.preventDefault();
                refresh();
              }}
            >
              <input
                className="topic-input"
                type="password"
                placeholder="Admin token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <button className="generate-btn" type="submit">Enter</button>
            </form>
            {error && <div className="error">{error}</div>}
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="page">
      <main className="main">
        <section className="hero">
          <div>
            <p className="eyebrow">Admin</p>
            <h2 className="hero-headline">Buyer list</h2>
            <p className="hero-sub">{list.length} buyer{list.length === 1 ? '' : 's'}.</p>
          </div>

          <form className="login-form" onSubmit={add} style={{ maxWidth: 520 }}>
            <input
              className="topic-input"
              type="email"
              placeholder="add-buyer@example.com"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              disabled={busy}
            />
            <div className="admin-ent-picker">
              <span style={{ fontSize: 13, opacity: 0.7 }}>Grant:</span>
              {knownEnts.map((ent) => (
                <label key={ent} className="admin-ent-check">
                  <input
                    type="checkbox"
                    checked={!!newEnts[ent]}
                    onChange={(e) => setNewEnts((s) => ({ ...s, [ent]: e.target.checked }))}
                    disabled={busy}
                  />
                  <span>{ent}</span>
                </label>
              ))}
            </div>
            <button className="generate-btn" type="submit" disabled={busy}>
              {busy ? 'Working…' : 'Add buyer'}
            </button>
          </form>
          {error && <div className="error">{error}</div>}
        </section>

        <section className="output">
          <article className="card">
            <header className="card-header">
              <h2 className="card-title">Authorized buyers</h2>
              <button className="copy-btn" onClick={refresh} disabled={busy}>Refresh</button>
            </header>
            <div className="card-body">
              {list.length === 0 ? (
                <p>No buyers yet.</p>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Entitlements</th>
                      <th>Source</th>
                      <th>Added</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((b) => {
                      const ents = Array.isArray(b.entitlements) ? b.entitlements : ['base'];
                      return (
                        <tr key={b.email}>
                          <td>{b.email}</td>
                          <td>
                            <div className="ent-badges">
                              {knownEnts.map((ent) => {
                                const has = ents.includes(ent);
                                return (
                                  <button
                                    key={ent}
                                    type="button"
                                    className={`ent-badge ${has ? 'is-on' : 'is-off'}`}
                                    onClick={() => has ? revoke(b.email, ent) : grant(b.email, ent)}
                                    disabled={busy}
                                    title={has ? `Revoke ${ent}` : `Grant ${ent}`}
                                  >
                                    {has ? '✓' : '+'} {ent}
                                  </button>
                                );
                              })}
                            </div>
                          </td>
                          <td>{b.source || b.event || '—'}</td>
                          <td>{b.addedAt ? new Date(b.addedAt).toLocaleString() : '—'}</td>
                          <td>
                            <button className="copy-btn" onClick={() => remove(b.email)} disabled={busy}>
                              Remove
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </article>
        </section>
      </main>

      <footer className="site-footer">
        <img className="footer-mark" src="/faceless48-mark.png" alt="Faceless 48" />
        <div className="footer-text">
          <div>© 2026 C3 Global</div>
        </div>
      </footer>
    </div>
  );
}
