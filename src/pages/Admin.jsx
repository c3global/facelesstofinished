import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchSession } from '../api.js';
import Footer from '../Footer.jsx';

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
  const [session, setSession] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [list, setList] = useState([]);
  const [totals, setTotals] = useState(null);
  const [signupsPerDay, setSignupsPerDay] = useState([]);
  const [knownEnts, setKnownEnts] = useState(['base', 'shorts']);
  const [newEmail, setNewEmail] = useState('');
  const [newEnts, setNewEnts] = useState({ base: true, shorts: false });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(() => new Set());

  const buildHeaders = () => {
    const h = { 'Content-Type': 'application/json' };
    if (token) h['X-Admin-Token'] = token;
    return h;
  };
  const headers = buildHeaders();

  const refresh = async () => {
    setError('');
    const res = await fetch('/api/admin-buyers', { headers: buildHeaders(), credentials: 'include' });
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
    const buyers = data.buyers || [];
    setList(buyers);
    setSelected((cur) => {
      const stillExisting = new Set(buyers.map((b) => b.email));
      const next = new Set();
      cur.forEach((email) => { if (stillExisting.has(email)) next.add(email); });
      return next;
    });
    setTotals(data.totals || null);
    setSignupsPerDay(Array.isArray(data.signupsPerDay) ? data.signupsPerDay : []);
    if (Array.isArray(data.knownEntitlements) && data.knownEntitlements.length) {
      setKnownEnts(data.knownEntitlements);
    }
    setAuthed(true);
    localStorage.setItem(TOKEN_KEY, token);
  };

  useEffect(() => {
    let cancelled = false;
    fetchSession()
      .then((s) => {
        if (cancelled) return;
        setSession(s);
        if (s?.isAdmin) {
          // Authenticated as admin via cookie — load straight away.
          refresh();
        } else if (token) {
          // Fall back to legacy token if one is saved.
          refresh();
        }
      })
      .finally(() => {
        if (!cancelled) setSessionLoading(false);
      });
    return () => { cancelled = true; };
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
      headers: buildHeaders(),
      credentials: 'include',
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
    const prev = list;
    setError('');
    setList((cur) =>
      cur.map((b) =>
        b.email === email
          ? { ...b, entitlements: Array.from(new Set([...(b.entitlements || []), entitlement])) }
          : b
      )
    );
    try {
      const res = await fetch('/api/admin-buyers?action=grant', {
        method: 'POST',
        headers: buildHeaders(),
        credentials: 'include',
        body: JSON.stringify({ email, entitlement }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      setList(prev);
      setError(`Failed to grant "${entitlement}" to ${email}: ${e.message}`);
      return;
    }
    refresh();
  };

  const revoke = async (email, entitlement) => {
    if (!confirm(`Revoke "${entitlement}" from ${email}?`)) return;
    const prev = list;
    setError('');
    setList((cur) =>
      cur.map((b) =>
        b.email === email
          ? { ...b, entitlements: (b.entitlements || []).filter((e) => e !== entitlement) }
          : b
      )
    );
    try {
      const res = await fetch('/api/admin-buyers?action=revoke', {
        method: 'POST',
        headers: buildHeaders(),
        credentials: 'include',
        body: JSON.stringify({ email, entitlement }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      setList(prev);
      setError(`Failed to revoke "${entitlement}" from ${email}: ${e.message}`);
      return;
    }
    refresh();
  };

  const deleteOne = async (email) => {
    const res = await fetch('/api/admin-buyers', {
      method: 'DELETE',
      headers: buildHeaders(),
      credentials: 'include',
      body: JSON.stringify({ email }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  };

  const remove = async (email) => {
    if (!confirm(`Remove ${email} entirely?`)) return;
    const prev = list;
    const prevTotals = totals;
    setError('');
    setList((cur) => cur.filter((b) => b.email !== email));
    if (totals && typeof totals.customers === 'number') {
      setTotals({ ...totals, customers: Math.max(0, totals.customers - 1) });
    }
    setSelected((cur) => {
      if (!cur.has(email)) return cur;
      const next = new Set(cur);
      next.delete(email);
      return next;
    });
    try {
      await deleteOne(email);
    } catch (e) {
      setList(prev);
      setTotals(prevTotals);
      setError(`Failed to remove ${email}: ${e.message}`);
      return;
    }
    refresh();
  };

  const removeSelected = async () => {
    if (selected.size === 0) return;
    const emails = Array.from(selected);
    if (!confirm(`Remove ${emails.length} buyer${emails.length === 1 ? '' : 's'} entirely?`)) return;
    const prev = list;
    const prevTotals = totals;
    setError('');
    const toRemove = new Set(emails);
    setList((cur) => cur.filter((b) => !toRemove.has(b.email)));
    if (totals && typeof totals.customers === 'number') {
      setTotals({ ...totals, customers: Math.max(0, totals.customers - emails.length) });
    }
    const results = await Promise.all(
      emails.map((email) => deleteOne(email).then(() => ({ email, ok: true })).catch((e) => ({ email, ok: false, err: e.message })))
    );
    const failed = results.filter((r) => !r.ok);
    if (failed.length > 0) {
      const failedEmails = new Set(failed.map((r) => r.email));
      // Roll back failed ones by restoring them from prev.
      setList((cur) => {
        const present = new Set(cur.map((b) => b.email));
        const restored = prev.filter((b) => failedEmails.has(b.email) && !present.has(b.email));
        return [...cur, ...restored];
      });
      // Roll back totals partially: only successes were actually removed.
      if (prevTotals && typeof prevTotals.customers === 'number') {
        const successes = emails.length - failed.length;
        setTotals({ ...prevTotals, customers: Math.max(0, prevTotals.customers - successes) });
      }
      setSelected(new Set(failed.map((r) => r.email)));
      setError(`Failed to remove: ${failed.map((r) => `${r.email} (${r.err})`).join(', ')}`);
    } else {
      setSelected(new Set());
    }
    refresh();
  };

  const toggleSelected = (email) => {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((cur) => {
      if (cur.size === list.length && list.length > 0) return new Set();
      return new Set(list.map((b) => b.email));
    });
  };

  if (sessionLoading) {
    return (
      <div className="page">
        <div className="loading-shell">Loading…</div>
      </div>
    );
  }

  if (!authed) {
    // Logged in but not an admin → show "Not authorized".
    if (session && !session.isAdmin) {
      return (
        <div className="page">
          <main className="main">
            <section className="login-card">
              <h2 className="hero-headline">Not authorized</h2>
              <p className="hero-sub">
                You're signed in as <strong>{session.email}</strong>, but this account
                isn't an admin.
              </p>
              <Link to="/" className="generate-btn">← Back to home</Link>
            </section>
          </main>
        </div>
      );
    }

    // Not logged in, or legacy admin-token entry path.
    return (
      <div className="page">
        <main className="main">
          <section className="login-card">
            <h2 className="hero-headline">Admin</h2>
            <p className="hero-sub">
              {session
                ? 'Enter your admin token to manage the buyer list.'
                : 'Sign in from the main app, or enter the admin token below.'}
            </p>
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
            {!session && (
              <p className="login-help" style={{ marginTop: 12 }}>
                <Link to="/">← Back to home</Link>
              </p>
            )}
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
              <div style={{ display: 'flex', gap: 8 }}>
                {selected.size > 0 && (
                  <button
                    className="copy-btn"
                    onClick={removeSelected}
                    style={{ background: '#c0392b', color: '#fff', borderColor: '#c0392b' }}
                  >
                    Delete selected ({selected.size})
                  </button>
                )}
                <button className="copy-btn" onClick={refresh}>Refresh</button>
              </div>
            </header>
            <div className="card-body">
              {list.length === 0 ? (
                <p>No buyers yet.</p>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}>
                        <input
                          type="checkbox"
                          aria-label="Select all"
                          checked={list.length > 0 && selected.size === list.length}
                          ref={(el) => {
                            if (el) el.indeterminate = selected.size > 0 && selected.size < list.length;
                          }}
                          onChange={toggleSelectAll}
                        />
                      </th>
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
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Select ${b.email}`}
                              checked={selected.has(b.email)}
                              onChange={() => toggleSelected(b.email)}
                            />
                          </td>
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

      <Footer />
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
