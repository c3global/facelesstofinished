import React, { useEffect, useMemo, useReducer, useRef } from 'react';
import { Link } from 'react-router-dom';
import { fetchSession } from '../api.js';
import Footer from '../Footer.jsx';
import ThemeToggle from '../ThemeToggle.jsx';

const TOKEN_KEY = 'f48_admin_token';
const DAY_MS = 24 * 60 * 60 * 1000;
const ROW_SUCCESS_FADE_MS = 2000;
const ACTIVITY_REFRESH_MS = 30000;

const initialState = {
  loading: false,
  error: null,
  session: null,
  sessionLoading: true,
  authed: false,
  token: '',
  buyers: [],
  totals: null,
  signupsPerDay: [],
  knownEntitlements: ['base', 'shorts', 'studio'],
  activity: [],
  activityLoading: false,
  activityFilter: null, // null | 'webhook' | 'grant' | 'webhook_failed'
  expandedActivity: null,
  replayed: {}, // { [activityId]: true }
  rowStatus: {}, // email -> 'idle' | 'pending' | 'success' | 'error'
  rowError: {}, // email -> string
  selected: new Set(),
  newBuyer: { email: '', entitlements: { base: true, shorts: false, studio: false } },
  activeTab: 'buyers',
  search: '',
  sort: 'added_desc',
  toast: null,
};

function reducer(state, action) {
  switch (action.type) {
    case 'set_session':
      return { ...state, session: action.session, sessionLoading: false };
    case 'set_token':
      return { ...state, token: action.token };
    case 'set_authed':
      return { ...state, authed: action.authed };
    case 'set_error':
      return { ...state, error: action.error };
    case 'set_loading':
      return { ...state, loading: action.loading };
    case 'set_buyers':
      return {
        ...state,
        buyers: action.buyers,
        totals: action.totals ?? state.totals,
        signupsPerDay: action.signupsPerDay ?? state.signupsPerDay,
        knownEntitlements: action.knownEntitlements ?? state.knownEntitlements,
      };
    case 'patch_buyer': {
      return {
        ...state,
        buyers: state.buyers.map((b) =>
          b.email === action.email ? { ...b, ...action.patch } : b
        ),
      };
    }
    case 'remove_buyers': {
      const removed = new Set(action.emails);
      const buyers = state.buyers.filter((b) => !removed.has(b.email));
      const selected = new Set(state.selected);
      action.emails.forEach((e) => selected.delete(e));
      return { ...state, buyers, selected };
    }
    case 'restore_buyers': {
      const present = new Set(state.buyers.map((b) => b.email));
      const restored = action.buyers.filter((b) => !present.has(b.email));
      return { ...state, buyers: [...state.buyers, ...restored] };
    }
    case 'set_row_status':
      return {
        ...state,
        rowStatus: { ...state.rowStatus, [action.email]: action.status },
        rowError:
          action.status === 'error'
            ? { ...state.rowError, [action.email]: action.error || 'error' }
            : (() => {
                const { [action.email]: _omit, ...rest } = state.rowError;
                return rest;
              })(),
      };
    case 'clear_row_status': {
      const { [action.email]: _omit, ...rest } = state.rowStatus;
      const { [action.email]: _omit2, ...rest2 } = state.rowError;
      return { ...state, rowStatus: rest, rowError: rest2 };
    }
    case 'toggle_selected': {
      const next = new Set(state.selected);
      if (next.has(action.email)) next.delete(action.email);
      else next.add(action.email);
      return { ...state, selected: next };
    }
    case 'set_selected':
      return { ...state, selected: action.selected };
    case 'set_new_buyer':
      return { ...state, newBuyer: { ...state.newBuyer, ...action.patch } };
    case 'reset_new_buyer':
      return {
        ...state,
        newBuyer: { email: '', entitlements: { base: true, shorts: false, studio: false } },
      };
    case 'set_tab':
      return { ...state, activeTab: action.tab };
    case 'set_search':
      return { ...state, search: action.search };
    case 'set_sort':
      return { ...state, sort: action.sort };
    case 'set_activity':
      return { ...state, activity: action.activity, activityLoading: false };
    case 'set_activity_loading':
      return { ...state, activityLoading: action.loading };
    case 'set_activity_filter':
      return { ...state, activityFilter: action.filter };
    case 'set_expanded_activity':
      return {
        ...state,
        expandedActivity: state.expandedActivity === action.id ? null : action.id,
      };
    case 'mark_replayed':
      return { ...state, replayed: { ...state.replayed, [action.id]: true } };
    case 'set_toast':
      return { ...state, toast: action.toast };
    default:
      return state;
  }
}

function formatMoney(cents) {
  const n = Number.isFinite(cents) ? cents : 0;
  return (n / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
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
    now - addedMs >= 14 * DAY_MS &&
    !Number.isFinite(lastLoginMs) &&
    !b.firstUseAt;
  if (isStuck) return { label: 'Stuck', color: '#c0392b' };
  if (isActive) return { label: 'Active', color: '#27ae60' };
  if (isNew) return { label: 'New', color: '#2980b9' };
  return null;
}

function sortBuyers(buyers, sort) {
  const arr = buyers.slice();
  switch (sort) {
    case 'email_asc':
      arr.sort((a, b) => a.email.localeCompare(b.email));
      break;
    case 'last_login_desc':
      arr.sort((a, b) => (Date.parse(b.lastLoginAt || 0) || 0) - (Date.parse(a.lastLoginAt || 0) || 0));
      break;
    case 'spend_desc':
      arr.sort((a, b) => (b.totalSpendCents || 0) - (a.totalSpendCents || 0));
      break;
    case 'added_desc':
    default:
      arr.sort((a, b) => (b.addedAt || '').localeCompare(a.addedAt || ''));
      break;
  }
  return arr;
}

export default function Admin() {
  const [state, dispatch] = useReducer(reducer, initialState, (init) => ({
    ...init,
    token: typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_KEY) || '' : '',
  }));
  const fadeTimers = useRef({});
  const activityIntervalRef = useRef(null);

  const buildHeaders = () => {
    const h = { 'Content-Type': 'application/json' };
    if (state.token) h['X-Admin-Token'] = state.token;
    return h;
  };

  const showToast = (message) => {
    dispatch({ type: 'set_toast', toast: message });
    setTimeout(() => dispatch({ type: 'set_toast', toast: null }), 3500);
  };

  const flashRowSuccess = (email) => {
    dispatch({ type: 'set_row_status', email, status: 'success' });
    clearTimeout(fadeTimers.current[email]);
    fadeTimers.current[email] = setTimeout(() => {
      dispatch({ type: 'clear_row_status', email });
    }, ROW_SUCCESS_FADE_MS);
  };

  const refresh = async () => {
    dispatch({ type: 'set_error', error: null });
    try {
      const res = await fetch('/api/admin-buyers', {
        headers: buildHeaders(),
        credentials: 'include',
      });
      if (res.status === 401) {
        dispatch({ type: 'set_authed', authed: false });
        dispatch({ type: 'set_error', error: 'Invalid admin token.' });
        localStorage.removeItem(TOKEN_KEY);
        return;
      }
      if (!res.ok) {
        let detail = '';
        try { detail = JSON.stringify(await res.json()); } catch { detail = await res.text().catch(() => ''); }
        dispatch({ type: 'set_error', error: `Failed to load (HTTP ${res.status}). ${detail}` });
        return;
      }
      const data = await res.json();
      dispatch({
        type: 'set_buyers',
        buyers: data.buyers || [],
        totals: data.totals || null,
        signupsPerDay: Array.isArray(data.signupsPerDay) ? data.signupsPerDay : [],
        knownEntitlements:
          Array.isArray(data.knownEntitlements) && data.knownEntitlements.length
            ? data.knownEntitlements
            : undefined,
      });
      dispatch({ type: 'set_authed', authed: true });
      localStorage.setItem(TOKEN_KEY, state.token);
    } catch (err) {
      dispatch({ type: 'set_error', error: `Network error: ${err.message}` });
    }
  };

  const fetchActivity = async () => {
    dispatch({ type: 'set_activity_loading', loading: true });
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (state.activityFilter) params.set('type', state.activityFilter);
      const res = await fetch(`/api/admin-activity?${params.toString()}`, {
        headers: buildHeaders(),
        credentials: 'include',
      });
      if (!res.ok) {
        dispatch({ type: 'set_activity', activity: [] });
        return;
      }
      const data = await res.json();
      dispatch({ type: 'set_activity', activity: Array.isArray(data.activity) ? data.activity : [] });
    } catch {
      dispatch({ type: 'set_activity', activity: [] });
    }
  };

  // Session bootstrap.
  useEffect(() => {
    let cancelled = false;
    fetchSession()
      .then((s) => {
        if (cancelled) return;
        dispatch({ type: 'set_session', session: s });
        if (s?.isAdmin || state.token) refresh();
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: 'set_session', session: null });
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-load + auto-refresh activity when tab is visible.
  useEffect(() => {
    if (!state.authed) return undefined;
    if (state.activeTab !== 'activity') {
      if (activityIntervalRef.current) {
        clearInterval(activityIntervalRef.current);
        activityIntervalRef.current = null;
      }
      return undefined;
    }
    fetchActivity();
    activityIntervalRef.current = setInterval(fetchActivity, ACTIVITY_REFRESH_MS);
    return () => {
      if (activityIntervalRef.current) {
        clearInterval(activityIntervalRef.current);
        activityIntervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.authed, state.activeTab, state.activityFilter]);

  // Buyer mutations -----------------------------------------------------
  const add = async (e) => {
    e?.preventDefault();
    const email = state.newBuyer.email.trim();
    if (!email) return;
    const entitlements = Object.entries(state.newBuyer.entitlements)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (entitlements.length === 0) {
      dispatch({ type: 'set_error', error: 'Pick at least one entitlement.' });
      return;
    }
    dispatch({ type: 'set_row_status', email, status: 'pending' });
    try {
      const res = await fetch('/api/admin-buyers', {
        method: 'POST',
        headers: buildHeaders(),
        credentials: 'include',
        body: JSON.stringify({ email, entitlements }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      dispatch({ type: 'reset_new_buyer' });
      flashRowSuccess(email);
      refresh();
    } catch (err) {
      dispatch({ type: 'set_row_status', email, status: 'error', error: err.message });
    }
  };

  const grant = async (email, entitlement) => {
    const prevBuyer = state.buyers.find((b) => b.email === email);
    dispatch({ type: 'set_row_status', email, status: 'pending' });
    dispatch({
      type: 'patch_buyer',
      email,
      patch: {
        entitlements: Array.from(new Set([...(prevBuyer?.entitlements || []), entitlement])),
      },
    });
    try {
      const res = await fetch('/api/admin-buyers?action=grant', {
        method: 'POST',
        headers: buildHeaders(),
        credentials: 'include',
        body: JSON.stringify({ email, entitlement }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      flashRowSuccess(email);
    } catch (err) {
      // Rollback.
      if (prevBuyer) {
        dispatch({ type: 'patch_buyer', email, patch: { entitlements: prevBuyer.entitlements } });
      }
      dispatch({ type: 'set_row_status', email, status: 'error', error: `grant ${entitlement}: ${err.message}` });
    }
  };

  const revoke = async (email, entitlement) => {
    if (!confirm(`Revoke "${entitlement}" from ${email}?`)) return;
    const prevBuyer = state.buyers.find((b) => b.email === email);
    dispatch({ type: 'set_row_status', email, status: 'pending' });
    dispatch({
      type: 'patch_buyer',
      email,
      patch: {
        entitlements: (prevBuyer?.entitlements || []).filter((e) => e !== entitlement),
      },
    });
    try {
      const res = await fetch('/api/admin-buyers?action=revoke', {
        method: 'POST',
        headers: buildHeaders(),
        credentials: 'include',
        body: JSON.stringify({ email, entitlement }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      flashRowSuccess(email);
    } catch (err) {
      if (prevBuyer) {
        dispatch({ type: 'patch_buyer', email, patch: { entitlements: prevBuyer.entitlements } });
      }
      dispatch({ type: 'set_row_status', email, status: 'error', error: `revoke ${entitlement}: ${err.message}` });
    }
  };

  const deleteOne = async (email) => {
    const res = await fetch(`/api/admin-buyers?email=${encodeURIComponent(email)}`, {
      method: 'DELETE',
      headers: buildHeaders(),
      credentials: 'include',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  };

  const remove = async (email) => {
    if (!confirm(`Remove ${email} entirely?`)) return;
    const prev = state.buyers;
    dispatch({ type: 'set_row_status', email, status: 'pending' });
    dispatch({ type: 'remove_buyers', emails: [email] });
    try {
      await deleteOne(email);
      showToast(`Removed ${email}`);
      refresh();
    } catch (err) {
      dispatch({ type: 'restore_buyers', buyers: prev.filter((b) => b.email === email) });
      dispatch({ type: 'set_row_status', email, status: 'error', error: err.message });
    }
  };

  const removeSelected = async () => {
    const emails = Array.from(state.selected);
    if (emails.length === 0) return;
    if (!confirm(`Remove ${emails.length} buyer${emails.length === 1 ? '' : 's'} entirely?`)) return;
    const prev = state.buyers;
    dispatch({ type: 'remove_buyers', emails });
    const results = await Promise.all(
      emails.map((email) =>
        deleteOne(email).then(() => ({ email, ok: true })).catch((e) => ({ email, ok: false, err: e.message }))
      )
    );
    const failed = results.filter((r) => !r.ok);
    if (failed.length > 0) {
      const failedEmails = new Set(failed.map((r) => r.email));
      dispatch({ type: 'restore_buyers', buyers: prev.filter((b) => failedEmails.has(b.email)) });
      showToast(
        `${results.length - failed.length} deleted, ${failed.length} failed (${failed.map((f) => `${f.email}: ${f.err}`).join('; ')})`
      );
    } else {
      showToast(`${results.length} deleted`);
    }
    refresh();
  };

  // Activity helpers ----------------------------------------------------
  const replayWebhook = async (activityId) => {
    try {
      const res = await fetch('/api/admin-activity?action=replay', {
        method: 'POST',
        headers: buildHeaders(),
        credentials: 'include',
        body: JSON.stringify({ activityId }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(`Replay failed: ${body.error || `HTTP ${res.status}`}`);
        return;
      }
      dispatch({ type: 'mark_replayed', id: activityId });
      showToast('Replayed successfully');
      fetchActivity();
    } catch (err) {
      showToast(`Replay error: ${err.message}`);
    }
  };

  // Derived view --------------------------------------------------------
  const filteredBuyers = useMemo(() => {
    let arr = state.buyers;
    const q = state.search.trim().toLowerCase();
    if (q) arr = arr.filter((b) => b.email.toLowerCase().includes(q));
    return sortBuyers(arr, state.sort);
  }, [state.buyers, state.search, state.sort]);

  // ---------------------------------------------------------------------
  if (state.sessionLoading) {
    return (
      <div className="page">
        <div className="loading-shell">Loading…</div>
      </div>
    );
  }

  if (!state.authed) {
    if (state.session && !state.session.isAdmin) {
      return (
        <div className="page">
          <main className="main">
            <section className="login-card">
              <h2 className="hero-headline">Not authorized</h2>
              <p className="hero-sub">
                You're signed in as <strong>{state.session.email}</strong>, but this account
                isn't an admin.
              </p>
              <Link to="/" className="generate-btn">← Back to home</Link>
            </section>
          </main>
        </div>
      );
    }
    return (
      <div className="page">
        <main className="main">
          <section className="login-card">
            <h2 className="hero-headline">Admin</h2>
            <p className="hero-sub">
              {state.session
                ? 'Enter your admin token to manage the buyer list.'
                : 'Sign in from the main app, or enter the admin token below.'}
            </p>
            <form
              className="login-form"
              onSubmit={(e) => { e.preventDefault(); refresh(); }}
            >
              <input
                className="topic-input"
                type="password"
                placeholder="Admin token"
                value={state.token}
                onChange={(e) => dispatch({ type: 'set_token', token: e.target.value })}
              />
              <button className="generate-btn" type="submit">Enter</button>
            </form>
            {!state.session && (
              <p className="login-help" style={{ marginTop: 12 }}>
                <Link to="/">← Back to home</Link>
              </p>
            )}
            {state.error && <div className="error">{state.error}</div>}
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="site-header">
        <a className="header-logo" href="/" aria-label="Faceless 48">
          <img src="/faceless48-lockup.png" alt="Faceless 48" />
        </a>
        <div className="title-block">
          <h1 className="title">Admin</h1>
        </div>
        <nav className="header-nav">
          <ThemeToggle />
        </nav>
      </header>

      <main className="main">
        <div className="admin-tabs">
          {[
            { id: 'buyers', label: 'Buyers' },
            { id: 'activity', label: 'Activity' },
            { id: 'stats', label: 'Stats' },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              className={`admin-tab ${state.activeTab === t.id ? 'is-selected' : ''}`}
              onClick={() => dispatch({ type: 'set_tab', tab: t.id })}
            >
              {t.label}
              {t.id === 'buyers' && state.buyers.length > 0 && (
                <span className="admin-tab-count">{state.buyers.length}</span>
              )}
            </button>
          ))}
        </div>

        {state.error && <div className="error">{state.error}</div>}
        {state.toast && <div className="admin-toast">{state.toast}</div>}

        {state.activeTab === 'buyers' && (
          <BuyersTab
            state={state}
            dispatch={dispatch}
            filteredBuyers={filteredBuyers}
            add={add}
            grant={grant}
            revoke={revoke}
            remove={remove}
            removeSelected={removeSelected}
            refresh={refresh}
          />
        )}

        {state.activeTab === 'activity' && (
          <ActivityTab
            state={state}
            dispatch={dispatch}
            fetchActivity={fetchActivity}
            replayWebhook={replayWebhook}
          />
        )}

        {state.activeTab === 'stats' && (
          <StatsTab
            totals={state.totals}
            knownEntitlements={state.knownEntitlements}
            signupsPerDay={state.signupsPerDay}
          />
        )}
      </main>

      <Footer />
    </div>
  );
}

// ============================================================
// Buyers tab
// ============================================================
function BuyersTab({ state, dispatch, filteredBuyers, add, grant, revoke, remove, removeSelected, refresh }) {
  const allVisibleSelected =
    filteredBuyers.length > 0 && filteredBuyers.every((b) => state.selected.has(b.email));
  const toggleSelectAll = () => {
    const next = new Set(state.selected);
    if (allVisibleSelected) {
      filteredBuyers.forEach((b) => next.delete(b.email));
    } else {
      filteredBuyers.forEach((b) => next.add(b.email));
    }
    dispatch({ type: 'set_selected', selected: next });
  };

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">Buyers</p>
          <h2 className="hero-headline">{state.buyers.length} total</h2>
        </div>
        <form className="login-form" onSubmit={add} style={{ maxWidth: 520 }}>
          <input
            className="topic-input"
            type="email"
            placeholder="add-buyer@example.com"
            value={state.newBuyer.email}
            onChange={(e) => dispatch({ type: 'set_new_buyer', patch: { email: e.target.value } })}
          />
          <div className="admin-ent-picker">
            <span style={{ fontSize: 13, opacity: 0.7 }}>Grant:</span>
            {state.knownEntitlements.map((ent) => (
              <label key={ent} className="admin-ent-check">
                <input
                  type="checkbox"
                  checked={!!state.newBuyer.entitlements[ent]}
                  onChange={(e) =>
                    dispatch({
                      type: 'set_new_buyer',
                      patch: {
                        entitlements: { ...state.newBuyer.entitlements, [ent]: e.target.checked },
                      },
                    })
                  }
                />
                <span>{ent}</span>
              </label>
            ))}
          </div>
          <button className="generate-btn" type="submit">Add buyer</button>
        </form>
      </section>

      <section className="output">
        <article className="card">
          <header className="card-header">
            <h2 className="card-title">Authorized buyers</h2>
            <div className="admin-toolbar">
              <input
                className="topic-input admin-search"
                type="search"
                placeholder="Filter by email…"
                value={state.search}
                onChange={(e) => dispatch({ type: 'set_search', search: e.target.value })}
              />
              <select
                className="admin-select"
                value={state.sort}
                onChange={(e) => dispatch({ type: 'set_sort', sort: e.target.value })}
              >
                <option value="added_desc">Added (newest)</option>
                <option value="email_asc">Email (A–Z)</option>
                <option value="last_login_desc">Last login</option>
                <option value="spend_desc">Spend</option>
              </select>
              {state.selected.size > 0 && (
                <button
                  className="copy-btn admin-danger"
                  onClick={removeSelected}
                  type="button"
                >
                  Delete selected ({state.selected.size})
                </button>
              )}
              <button className="copy-btn" onClick={refresh} type="button">Sync</button>
            </div>
          </header>
          <div className="card-body">
            {filteredBuyers.length === 0 ? (
              <p>No buyers match.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th style={{ width: 28 }}>
                      <input
                        type="checkbox"
                        aria-label="Select all visible"
                        checked={allVisibleSelected}
                        ref={(el) => {
                          if (el) {
                            const someSelected = filteredBuyers.some((b) => state.selected.has(b.email));
                            el.indeterminate = someSelected && !allVisibleSelected;
                          }
                        }}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Entitlements</th>
                    <th>Last login</th>
                    <th>S/Sh</th>
                    <th>Spend</th>
                    <th>Source</th>
                    <th>Added</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBuyers.map((b) => (
                    <BuyerRow
                      key={b.email}
                      buyer={b}
                      state={state}
                      dispatch={dispatch}
                      grant={grant}
                      revoke={revoke}
                      remove={remove}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </article>
      </section>
    </>
  );
}

function BuyerRow({ buyer, state, dispatch, grant, revoke, remove }) {
  const ents = Array.isArray(buyer.entitlements) ? buyer.entitlements : ['base'];
  const badge = rowBadge(buyer);
  const lastLoginLabel =
    buyer.daysSinceLastLogin == null
      ? 'Never'
      : buyer.daysSinceLastLogin === 0
      ? 'Today'
      : `${buyer.daysSinceLastLogin}d ago`;

  const status = state.rowStatus[buyer.email] || 'idle';
  const err = state.rowError[buyer.email];

  return (
    <tr>
      <td>
        <input
          type="checkbox"
          aria-label={`Select ${buyer.email}`}
          checked={state.selected.has(buyer.email)}
          onChange={() => dispatch({ type: 'toggle_selected', email: buyer.email })}
        />
      </td>
      <td>
        <div className="admin-email-cell">
          <span>{buyer.email}</span>
          <StatusPill status={status} error={err} />
        </div>
      </td>
      <td>
        {badge ? (
          <span className="admin-status-badge" style={{ background: badge.color }}>
            {badge.label}
          </span>
        ) : (
          '—'
        )}
      </td>
      <td>
        <div className="ent-badges">
          {state.knownEntitlements.map((ent) => {
            const has = ents.includes(ent);
            return (
              <button
                key={ent}
                type="button"
                className={`ent-badge ${has ? 'is-on' : 'is-off'}`}
                onClick={() => (has ? revoke(buyer.email, ent) : grant(buyer.email, ent))}
                title={has ? `Revoke ${ent}` : `Grant ${ent}`}
              >
                {has ? '✓' : '+'} {ent}
              </button>
            );
          })}
        </div>
      </td>
      <td>{lastLoginLabel}</td>
      <td>{(buyer.scriptCount || 0)} / {(buyer.shortsCount || 0)}</td>
      <td>{formatMoney(buyer.totalSpendCents)}</td>
      <td>{buyer.source || buyer.event || '—'}</td>
      <td>{buyer.addedAt ? new Date(buyer.addedAt).toLocaleDateString() : '—'}</td>
      <td>
        <button className="copy-btn" onClick={() => remove(buyer.email)} type="button">
          Remove
        </button>
      </td>
    </tr>
  );
}

function StatusPill({ status, error }) {
  if (status === 'idle' || !status) return <span className="admin-row-pill is-idle">—</span>;
  if (status === 'pending') return <span className="admin-row-pill is-pending">Saving…</span>;
  if (status === 'success') return <span className="admin-row-pill is-success">✓</span>;
  if (status === 'error') {
    return (
      <span className="admin-row-pill is-error" title={error || 'error'}>
        ✕ {error ? error.slice(0, 40) : 'error'}
      </span>
    );
  }
  return null;
}

// ============================================================
// Activity tab
// ============================================================
function ActivityTab({ state, dispatch, fetchActivity, replayWebhook }) {
  const filters = [
    { id: null, label: 'All' },
    { id: 'webhook', label: 'Webhooks' },
    { id: 'grant', label: 'Grants' },
    { id: 'webhook_failed', label: 'Failures' },
  ];

  return (
    <section className="output">
      <article className="card">
        <header className="card-header">
          <h2 className="card-title">Activity log</h2>
          <div className="admin-toolbar">
            {filters.map((f) => (
              <button
                key={f.id || 'all'}
                type="button"
                className={`activity-filter ${state.activityFilter === f.id ? 'is-selected' : ''}`}
                onClick={() => dispatch({ type: 'set_activity_filter', filter: f.id })}
              >
                {f.label}
              </button>
            ))}
            <button className="copy-btn" onClick={fetchActivity} type="button">Refresh</button>
          </div>
        </header>
        <div className="card-body">
          {state.activityLoading && state.activity.length === 0 ? (
            <p>Loading activity…</p>
          ) : state.activity.length === 0 ? (
            <p>No activity recorded yet.</p>
          ) : (
            <table className="admin-table activity-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Email</th>
                  <th>Actor</th>
                  <th>Summary</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {state.activity.map((entry) => (
                  <ActivityRow
                    key={entry.id}
                    entry={entry}
                    expanded={state.expandedActivity === entry.id}
                    replayed={!!state.replayed[entry.id]}
                    onToggle={() => dispatch({ type: 'set_expanded_activity', id: entry.id })}
                    onReplay={() => replayWebhook(entry.id)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </article>
    </section>
  );
}

function ActivityRow({ entry, expanded, replayed, onToggle, onReplay }) {
  const ts = entry.ts ? new Date(entry.ts).toLocaleString() : '—';
  const summary = (() => {
    const d = entry.detail || {};
    if (entry.type === 'webhook') {
      const products = Array.isArray(d.products) ? d.products.join(', ') : '';
      return `${d.event || 'order'}${products ? ` → ${products}` : ''}${d.replay ? ' (replay)' : ''}`;
    }
    if (entry.type === 'webhook_failed') {
      return `${d.reason || 'failed'}${d.httpStatus ? ` (HTTP ${d.httpStatus})` : ''}`;
    }
    if (entry.type === 'grant' || entry.type === 'revoke') {
      return d.entitlement || '—';
    }
    if (entry.type === 'add') {
      return Array.isArray(d.entitlements) ? d.entitlements.join(', ') : '—';
    }
    return '—';
  })();

  const canReplay = entry.type === 'webhook_failed' || entry.type === 'webhook';

  return (
    <>
      <tr>
        <td style={{ whiteSpace: 'nowrap' }}>{ts}</td>
        <td><TypeBadge type={entry.type} /></td>
        <td>{entry.email || '—'}</td>
        <td style={{ opacity: 0.75 }}>{entry.actor || '—'}</td>
        <td style={{ fontSize: 13 }}>{summary}</td>
        <td>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="copy-btn" type="button" onClick={onToggle}>
              {expanded ? 'Hide' : 'Details'}
            </button>
            {canReplay && (
              <button className="copy-btn" type="button" onClick={onReplay}>
                {replayed ? '✓ Replayed' : 'Replay'}
              </button>
            )}
          </div>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6}>
            <pre className="activity-detail">{JSON.stringify(entry, null, 2)}</pre>
          </td>
        </tr>
      )}
    </>
  );
}

function TypeBadge({ type }) {
  const map = {
    webhook: { bg: '#1D9E75', label: 'webhook' },
    webhook_failed: { bg: '#C41A18', label: 'failed' },
    grant: { bg: '#378ADD', label: 'grant' },
    revoke: { bg: '#7F4FDD', label: 'revoke' },
    remove: { bg: '#666', label: 'remove' },
    add: { bg: '#2980b9', label: 'add' },
  };
  const m = map[type] || { bg: '#888', label: type };
  return (
    <span className="admin-status-badge" style={{ background: m.bg }}>{m.label}</span>
  );
}

// ============================================================
// Stats tab
// ============================================================
function StatsTab({ totals, knownEntitlements, signupsPerDay }) {
  if (!totals) {
    return (
      <section className="output">
        <article className="card">
          <div className="card-body"><p>No stats yet.</p></div>
        </article>
      </section>
    );
  }
  return (
    <section className="output">
      <article className="card">
        <header className="card-header">
          <h2 className="card-title">Stats</h2>
        </header>
        <div className="card-body">
          <div
            className="admin-stats-banner"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
              gap: 12,
              width: '100%',
              margin: '0 0 16px',
            }}
          >
            <StatTile label="Customers" value={totals.customers} />
            {knownEntitlements.map((ent) => (
              <StatTile key={ent} label={ent} value={totals.byEntitlement?.[ent] ?? 0} />
            ))}
            <StatTile label="Active 7d" value={totals.activeLast7d} />
            <StatTile label="Active 30d" value={totals.activeLast30d} />
            <StatTile label="Revenue" value={formatMoney(totals.revenueCents)} />
            <StatTile label="Scripts" value={totals.scriptsGenerated} />
            <StatTile label="Shorts" value={totals.shortsGenerated} />
            <StatTile label="Conv. → shorts" value={formatPct(totals.conversionToShorts)} />
            <StatTile label="Stuck" value={totals.stuckCustomers} />
            <StatTile label="Activated" value={totals.activatedCustomers} />
          </div>
          {signupsPerDay.length > 0 && <SignupsChart data={signupsPerDay} />}
        </div>
      </article>
    </section>
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
                background: d.count > 0 ? 'var(--primary)' : 'rgba(127,127,127,0.18)',
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
