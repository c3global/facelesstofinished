import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Search, RefreshCw, Download, ChevronDown, ChevronRight } from "lucide-react";
import { apiClient } from "../../App";

function fmtCents(c) {
  if (!c) return "$0";
  return `$${(c / 100).toFixed(2)}`;
}
function fmtDate(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return s;
  }
}
function fmtDateTime(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return s;
  }
}

const TIER_LABELS = {
  t1: "Script Engine",
  t2: "Scripts + Shorts",
  t3: "Studio Pro",
  t4: "Studio Pro + BYOK",
  founder: "Founder",
};

const SORT_COLS = [
  { key: "email", label: "Email" },
  { key: "scripts_total", label: "Scripts" },
  { key: "renders_total", label: "Renders" },
  { key: "thumbnails_total", label: "Thumbnails" },
  { key: "spend_cents", label: "Spend" },
  { key: "last_seen", label: "Last seen" },
  { key: "added_at", label: "Joined" },
];

/**
 * Per-customer Usage leaderboard. Joins /admin/usage rows w/ inline
 * drill-down rows so admins can answer "who's actually generating?" at a
 * glance. Pairs with the Buyers tab (auth/entitlement state) and the Stats
 * tab (high-level totals + chart).
 */
export default function UsageTab() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [sortBy, setSortBy] = useState("last_seen");
  const [sortDir, setSortDir] = useState("desc");
  const [expanded, setExpanded] = useState(() => new Set());
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  }, []);

  // Defensively normalize an axios error into a single human string. FastAPI
  // returns Pydantic 422 errors as Array<{loc, msg, type, …}>, which React
  // refuses to render directly ("Objects are not valid as a React child").
  // This helper handles strings, arrays of validation errors, and unknown
  // dict shapes uniformly so the toast never crashes the tree.
  const extractErrMsg = (e, fallback = "Something went wrong") => {
    const detail = e?.response?.data?.detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (d?.msg || JSON.stringify(d))).join("; ");
    }
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      return detail.message || JSON.stringify(detail);
    }
    return e?.message || fallback;
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { sort_by: sortBy, sort_dir: sortDir, limit: 500 };
      if (q.trim()) params.q = q.trim();
      const r = await apiClient.get("/admin/usage", { params });
      setItems(r.data.items || []);
      setTotal(r.data.total || 0);
    } catch (e) {
      showToast(extractErrMsg(e, "Failed to load usage"), "err");
    } finally {
      setLoading(false);
    }
  }, [q, sortBy, sortDir, showToast]);

  useEffect(() => { load(); }, [load]);

  const downloadCSV = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const r = await apiClient.get("/admin/usage/export", { responseType: "blob" });
      const blob = new Blob([r.data], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const today = new Date().toISOString().slice(0, 10);
      const a = document.createElement("a");
      a.href = url;
      a.download = `F2F48-usage-${today}-export.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast("Usage CSV downloaded");
    } catch (e) {
      showToast(extractErrMsg(e, "CSV export failed"), "err");
    } finally {
      setExporting(false);
    }
  };

  const toggleExpand = (email) => {
    const next = new Set(expanded);
    if (next.has(email)) next.delete(email);
    else next.add(email);
    setExpanded(next);
  };

  const totals = useMemo(() => {
    let scripts = 0, renders = 0, thumbnails = 0, spend = 0, founders = 0;
    for (const r of items) {
      scripts    += r.scripts?.total    || 0;
      renders    += r.renders?.total    || 0;
      thumbnails += r.thumbnails?.total || 0;
      spend      += r.spend_cents       || 0;
      if (r.founder) founders++;
    }
    return { scripts, renders, thumbnails, spend, founders };
  }, [items]);

  const toggleSort = (col) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
  };

  return (
    <div className="admin-section" data-testid="usage-tab">
      <div className="admin-toolbar">
        <div className="admin-search">
          <Search size={14} />
          <input
            type="text"
            placeholder="Search by email…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            data-testid="usage-search"
          />
        </div>
        <button className="admin-btn" onClick={load} data-testid="usage-refresh">
          <RefreshCw size={13} /> Refresh
        </button>
        <button
          className="admin-btn"
          onClick={downloadCSV}
          disabled={exporting}
          data-testid="usage-export-csv"
          title="Download per-customer usage as CSV (F2F48-usage-YYYY-MM-DD-export.csv)"
        >
          <Download size={13} /> {exporting ? "Exporting…" : "Export CSV"}
        </button>
        <span className="admin-meta" data-testid="usage-total">
          {total} customers · {totals.scripts.toLocaleString()} scripts ·{" "}
          {totals.renders.toLocaleString()} renders ·{" "}
          {totals.thumbnails.toLocaleString()} thumbnails · {fmtCents(totals.spend)} infra
        </span>
      </div>

      <div className="admin-table-wrap">
        <table className="admin-table usage-table" data-testid="usage-table">
          <thead>
            <tr>
              <th style={{ width: 32 }} />
              {SORT_COLS.map((c) => (
                <th
                  key={c.key}
                  className={`usage-th-sortable ${sortBy === c.key ? "is-active" : ""}`}
                  onClick={() => toggleSort(c.key)}
                  data-testid={`usage-th-${c.key}`}
                  title={`Sort by ${c.label}`}
                >
                  {c.label}{sortBy === c.key ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
                </th>
              ))}
              <th>Tier</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={9} className="admin-empty">Loading…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={9} className="admin-empty">No customers found.</td></tr>
            )}
            {!loading && items.map((row) => {
              const open = expanded.has(row.email);
              return (
                <React.Fragment key={row.email}>
                  <tr
                    className={`usage-row ${open ? "is-open" : ""}`}
                    data-testid={`usage-row-${row.email}`}
                    onClick={() => toggleExpand(row.email)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </td>
                    <td className="admin-td-email">
                      {row.email}
                      {row.founder && <span className="ent-chip ent-chip-founder" style={{ marginLeft: 6 }}>founder</span>}
                    </td>
                    <td>{row.scripts?.total ?? 0}</td>
                    <td>{row.renders?.total ?? 0}</td>
                    <td data-testid={`usage-thumbs-${row.email}`}>{row.thumbnails?.total ?? 0}</td>
                    <td>{fmtCents(row.spend_cents)}</td>
                    <td>{fmtDate(row.last_seen)}</td>
                    <td>{fmtDate(row.added_at)}</td>
                    <td>
                      <span className={`ent-chip ent-chip-${row.tier || "t1"}`}>
                        {TIER_LABELS[row.tier] || row.tier || "—"}
                      </span>
                    </td>
                  </tr>
                  {open && (
                    <tr className="usage-drilldown-row" data-testid={`usage-drilldown-${row.email}`}>
                      <td colSpan={9}>
                        <div className="usage-drilldown">
                          <div className="usage-drilldown-grid">
                            <div className="usage-card">
                              <h4>Scripts</h4>
                              <div className="usage-num">{row.scripts?.total ?? 0}</div>
                              <div className="usage-breakdown">
                                <span>Long: <b>{row.scripts?.long ?? 0}</b></span>
                                <span>Shorts: <b>{row.scripts?.shorts ?? 0}</b></span>
                                <span>Sprints: <b>{row.scripts?.sprint ?? 0}</b></span>
                              </div>
                              <div className="usage-mute">Last: {fmtDateTime(row.scripts?.last_at)}</div>
                            </div>
                            <div className="usage-card">
                              <h4>Renders</h4>
                              <div className="usage-num">{row.renders?.total ?? 0}</div>
                              <div className="usage-breakdown">
                                <span>Faceless: <b>{row.renders?.faceless ?? 0}</b></span>
                                <span>Avatar: <b>{row.renders?.avatar ?? 0}</b></span>
                                <span>Complete: <b>{row.renders?.complete ?? 0}</b></span>
                                <span>Failed: <b>{row.renders?.failed ?? 0}</b></span>
                              </div>
                              <div className="usage-mute">Last: {fmtDateTime(row.renders?.last_at)}</div>
                            </div>
                            <div className="usage-card" data-testid={`usage-drilldown-thumbs-${row.email}`}>
                              <h4>Thumbnails</h4>
                              <div className="usage-num">{row.thumbnails?.total ?? 0}</div>
                              <div className="usage-breakdown">
                                <span>Premium: <b>{row.thumbnails?.premium ?? 0}</b></span>
                                <span>Fast: <b>{row.thumbnails?.fast ?? 0}</b></span>
                              </div>
                              <div className="usage-mute">Last: {fmtDateTime(row.thumbnails?.last_at)}</div>
                            </div>
                            <div className="usage-card">
                              <h4>Spend</h4>
                              <div className="usage-num">{fmtCents(row.spend_cents)}</div>
                              <div className="usage-breakdown">
                                <span>Buyer total: <b>{fmtCents(row.buyer_total_spend_cents)}</b></span>
                                <span>Logins: <b>{row.login_count ?? 0}</b></span>
                              </div>
                              <div className="usage-mute">Tier: {TIER_LABELS[row.tier] || row.tier}</div>
                            </div>
                            <div className="usage-card">
                              <h4>Entitlements</h4>
                              <div className="ent-chips" style={{ marginTop: 8 }}>
                                {(row.entitlements || []).map((e) => (
                                  <span key={e} className={`ent-chip ent-chip-${e}`}>{e}</span>
                                ))}
                                {(row.entitlements || []).length === 0 && (
                                  <span className="usage-mute">No entitlements</span>
                                )}
                              </div>
                              <div className="usage-mute" style={{ marginTop: 12 }}>
                                Joined {fmtDate(row.added_at)}
                              </div>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {toast && (
        <div className={`admin-toast is-${toast.kind}`} data-testid="admin-toast" role="status">
          {toast.msg}
        </div>
      )}
    </div>
  );
}
