import React, { useEffect, useState } from 'react';

const TOKEN_KEY = 'f48_admin_token';
const DAY_MS = 24 * 60 * 60 * 1000;

function formatMoney(cents) {
  const n = Number.isFinite(cents) ? cents : 0;
  return (n / 100).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
  });
}

function formatPct(frac) {
  const n = Number.isFinite(frac) ? frac : 0;
  return `${(n * 100).toFixed(1)}%`;
}

function rowBadge(b) {
  const now = Date.now();
  const addedMs = b.addedAt ? Date.parse(b.addedAt) : NaN;
  const lastLoginMs = b.lastLoginAt ? Date.parse(b.lastLoginAt) : NaN;
  const isNew =
    Number.isFinite(addedMs) && now - addedMs <= 7 * DAY_MS && !b.firstUseAt;
  const isActive =
    Number.isFinite(lastLoginMs) && now - lastLoginMs <= 7 * DAY_MS;
  const isStuck =
    Number.isFinite(addedMs) &&
    now - addedMs >= 7 * DAY_MS &&
    !Number.isFinite(lastLoginMs);
  if (isStuck) return { label: 'Stuck', color: '#c0392b' };
  if (isActive) return { label: 'Active', color: '#27ae60' };
  if (isNew) return { label: 'New', color: '#2980b9' };
  return null;
}

export default function Admin() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || '');
  const [authed, setAuthed] = useState(false);
  const [list, setList] = useState([]);
  const [totals, setTotals] = useState(null);
  const [signupsPerDay, setSignupsPerDay] = useState([]);
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
    setTotals(data.totals || null);
    setSignupsPerDay(Array.isArray(data.signupsPerDay) ? data.signupsPerDay : []);
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

          {totals && (
            <div
              className="admin-stats-banner"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 12,
                width: '100%',
                margin: '12px 0',
              }}
            >
              <StatTile label="Customers" value={totals.customers} />
              {knownEnts.map((ent) => (
                <StatTile
                  key={ent}
                  label={ent}
                  value={totals.byEntitlement?.[ent] ?? 0}
                />
              ))}
              <StatTile label="Active 7d" value={totals.activeLast7d} />
              <StatTile label="Active 30d" value={totals.activeLast30d} />
              <StatTile label="Revenue" value={formatMoney(totals.revenueCents)} />
              <StatTile label="Scripts" value={totals.scriptsGenerated} />
              <StatTile label="Shorts" value={totals.shortsGenerated} />
              <StatTile
                label="Conv. → shorts"
                value={formatPct(totals.conversionToShorts)}
              />
              <StatTile label="Stuck" value={totals.stuckCustomers} />
              <StatTile label="Activated" value={totals.activatedCustomers} />
            </div>
          )}

          {signupsPerDay.length > 0 && (
            <SignupsChart data={signupsPerDay} />
          )}

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
                      <th>Status</th>
                      <th>Entitlements</th>
                      <th>Last login</th>
                      <th>Scripts / Shorts</th>
                      <th>Spend</th>
                      <th>Source</th>
                      <th>Added</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((b) => {
                      const ents = Array.isArray(b.entitlements) ? b.entitlements : ['base'];
                      const badge = rowBadge(b);
                      const lastLoginLabel =
                        b.daysSinceLastLogin == null
                          ? 'Never'
                          : b.daysSinceLastLogin === 0
                          ? 'Today'
                          : `${b.daysSinceLastLogin}d ago`;
                      return (
                        <tr key={b.email}>
                          <td>{b.email}</td>
                          <td>
                            {badge ? (
                              <span
                                style={{
                                  display: 'inline-block',
                                  padding: '2px 8px',
                                  borderRadius: 10,
                                  fontSize: 11,
                                  color: '#fff',
                                  background: badge.color,
                                }}
                              >
                                {badge.label}
                              </span>
                            ) : (
                              '—'
                            )}
                          </td>
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
                          <td>{lastLoginLabel}</td>
                          <td>
                            {(b.scriptCount || 0)} / {(b.shortsCount || 0)}
                          </td>
                          <td>{formatMoney(b.totalSpendCents)}</td>
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

function StatTile({ label, value }) {
  return (
    <div
      style={{
        padding: '10px 12px',
        borderRadius: 8,
        background: 'rgba(127,127,127,0.08)',
        border: '1px solid rgba(127,127,127,0.18)',
      }}
    >
      <div style={{ fontSize: 11, opacity: 0.6, textTransform: 'uppercase', letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 600, marginTop: 2 }}>{value}</div>
    </div>
  );
}

function SignupsChart({ data }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div style={{ width: '100%', margin: '12px 0' }}>
      <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>
        Signups, last 30 days (max {max}/day)
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          gap: 2,
          height: 60,
          padding: '4px 0',
          borderBottom: '1px solid rgba(127,127,127,0.25)',
        }}
      >
        {data.map((d) => {
          const h = Math.round((d.count / max) * 100);
          return (
            <div
              key={d.date}
              title={`${d.date}: ${d.count}`}
              style={{
                flex: 1,
                height: `${Math.max(2, h)}%`,
                background: d.count > 0 ? '#4a90e2' : 'rgba(127,127,127,0.18)',
                borderRadius: 2,
              }}
            />
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, opacity: 0.5, marginTop: 4 }}>
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </div>
    </div>
  );
}
