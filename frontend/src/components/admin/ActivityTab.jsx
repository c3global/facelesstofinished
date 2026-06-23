import React, { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Repeat, Trash2, AlertTriangle } from "lucide-react";
import { apiClient } from "../../App";

const TYPES = [
  "", // all
  "webhook",
  "webhook_failed",
  "admin_grant",
  "admin_revoke",
  "admin_delete_buyer",
  "admin_bulk_delete",
  "admin_buyers_import",
  "admin_replay",
  "admin_delete_activity",
  "admin_bulk_delete_activity",
  "admin_wipe_activity",
  "studio_render",
  "studio_render_deleted",
];

function fmtTs(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

export default function ActivityTab() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState("");
  const [filterEmail, setFilterEmail] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [toast, setToast] = useState(null);
  const [wipeConfirm, setWipeConfirm] = useState(false);

  const showToast = useCallback((msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (filterType) params.type = filterType;
      if (filterEmail.trim()) params.email = filterEmail.trim();
      if (dateFrom) params.date_from = new Date(dateFrom).toISOString();
      if (dateTo) {
        const d = new Date(dateTo);
        d.setHours(23, 59, 59, 999);
        params.date_to = d.toISOString();
      }
      const r = await apiClient.get("/admin/activity", { params });
      setItems(r.data.items || []);
      setTotal(r.data.total || 0);
      setSelected(new Set());
    } catch (e) {
      showToast(e?.response?.data?.detail || "Failed to load activity", "err");
    } finally {
      setLoading(false);
    }
  }, [filterType, filterEmail, dateFrom, dateTo, showToast]);

  useEffect(() => {
    load();
  }, [load]);

  // Silent auto-refresh — same low-overhead pattern as BuyersTab so the
  // Activity feed surfaces webhook events, render completions, and admin
  // actions in real time while the tab is open. Pauses on hidden tabs;
  // refreshes immediately on tab focus. Per Charity's 2026-02-23 follow-up:
  // "that should've automatically been added [to Activity too]."
  useEffect(() => {
    let stop = false;
    const tick = () => {
      if (stop) return;
      if (typeof document !== "undefined" && document.hidden) return;
      load();
    };
    const id = setInterval(tick, 20_000);
    const onVis = () => {
      if (!document.hidden) load();
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVis);
    }
    return () => {
      stop = true;
      clearInterval(id);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVis);
      }
    };
  }, [load]);

  const allSelected = useMemo(
    () => items.length > 0 && items.every((a) => selected.has(a.id)),
    [items, selected],
  );
  const toggleAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(items.map((a) => a.id)));
  };
  const toggleOne = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const replay = async (id) => {
    if (!window.confirm("Replay this failed webhook? It will be re-processed locally.")) return;
    try {
      const r = await apiClient.post(`/admin/activity/${encodeURIComponent(id)}/replay`);
      showToast(`Replayed — ${JSON.stringify(r.data.result)}`);
      load();
    } catch (e) {
      showToast(e?.response?.data?.detail || "Replay failed", "err");
    }
  };

  const deleteOne = async (id) => {
    if (!window.confirm("Delete this activity event?")) return;
    const prev = items;
    setItems((cur) => cur.filter((a) => a.id !== id));
    try {
      await apiClient.delete(`/admin/activity/${encodeURIComponent(id)}`);
      showToast("Deleted");
    } catch (e) {
      setItems(prev);
      showToast(e?.response?.data?.detail || "Delete failed", "err");
    }
  };

  const bulkDelete = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    if (!window.confirm(`Delete ${ids.length} event(s)? This cannot be undone.`)) return;
    const prev = items;
    setItems((cur) => cur.filter((a) => !selected.has(a.id)));
    setSelected(new Set());
    try {
      const r = await apiClient.post("/admin/activity/bulk-delete", { ids });
      showToast(`Deleted ${r.data.deleted} event(s)`);
    } catch (e) {
      setItems(prev);
      showToast(e?.response?.data?.detail || "Bulk delete failed", "err");
    }
  };

  const wipeAll = async () => {
    setWipeConfirm(false);
    try {
      const r = await apiClient.post("/admin/activity/bulk-delete", { wipe_all: true });
      showToast(`Wiped — ${r.data.deleted} event(s) deleted`);
      load();
    } catch (e) {
      showToast(e?.response?.data?.detail || "Wipe failed", "err");
    }
  };

  return (
    <div className="admin-section" data-testid="activity-tab">
      <div className="admin-toolbar">
        <select
          className="admin-select"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          data-testid="activity-filter-type"
        >
          {TYPES.map((t) => (
            <option key={t} value={t}>{t || "All event types"}</option>
          ))}
        </select>
        <input
          type="text"
          className="admin-input"
          placeholder="Filter by email…"
          value={filterEmail}
          onChange={(e) => setFilterEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          data-testid="activity-filter-email"
        />
        <input
          type="date"
          className="admin-input"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          aria-label="From date"
          data-testid="activity-filter-from"
        />
        <input
          type="date"
          className="admin-input"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          aria-label="To date"
          data-testid="activity-filter-to"
        />
        <button className="admin-btn" onClick={load} data-testid="activity-refresh">
          <RefreshCw size={13} /> Refresh
        </button>
        {selected.size > 0 && (
          <button
            className="admin-btn is-danger"
            onClick={bulkDelete}
            data-testid="activity-bulk-delete"
          >
            <Trash2 size={13} /> Delete {selected.size}
          </button>
        )}
        <button
          className="admin-btn is-danger"
          onClick={() => setWipeConfirm(true)}
          data-testid="activity-wipe-all"
          title="Delete every activity event (cannot be undone)"
        >
          <AlertTriangle size={13} /> Wipe all
        </button>
        <span className="admin-meta" data-testid="activity-total">{total} events</span>
      </div>

      <div className="admin-table-wrap">
        <table className="admin-table" data-testid="activity-table">
          <thead>
            <tr>
              <th className="admin-th-checkbox">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label="Select all events"
                  data-testid="activity-select-all"
                />
              </th>
              <th>Time</th>
              <th>Type</th>
              <th>Email</th>
              <th>Detail</th>
              <th className="admin-th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="admin-empty">Loading…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={6} className="admin-empty">No activity matches these filters.</td></tr>
            )}
            {!loading && items.map((a) => {
              const isFailed = a.type === "webhook_failed";
              const isExpanded = expanded === a.id;
              const detailStr = a.detail ? JSON.stringify(a.detail) : "";
              return (
                <React.Fragment key={a.id}>
                  <tr
                    className={`activity-row ${isFailed ? "is-failed" : ""}`}
                    data-testid={`activity-row-${a.id}`}
                  >
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.has(a.id)}
                        onChange={() => toggleOne(a.id)}
                        aria-label={`Select event ${a.id}`}
                        data-testid={`activity-select-${a.id}`}
                      />
                    </td>
                    <td className="admin-td-ts">{fmtTs(a.ts)}</td>
                    <td>
                      <span className={`activity-type-pill activity-type-${a.type}`}>{a.type}</span>
                    </td>
                    <td className="admin-td-email">{a.email || "—"}</td>
                    <td className="admin-td-detail">
                      <button
                        className="activity-detail-toggle"
                        onClick={() => setExpanded(isExpanded ? null : a.id)}
                        data-testid={`activity-detail-${a.id}`}
                      >
                        {isExpanded ? "Hide" : "Show"} ({detailStr.length} chars)
                      </button>
                    </td>
                    <td>
                      <div className="activity-actions">
                        {isFailed && (
                          <button
                            className="admin-btn is-small is-warning"
                            onClick={() => replay(a.id)}
                            data-testid={`replay-${a.id}`}
                            title="Re-process this failed webhook locally (idempotent)"
                          >
                            <Repeat size={12} /> Replay
                          </button>
                        )}
                        <button
                          className="admin-icon-btn"
                          onClick={() => deleteOne(a.id)}
                          aria-label="Delete event"
                          data-testid={`activity-delete-${a.id}`}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="activity-detail-row" data-testid={`activity-detail-row-${a.id}`}>
                      <td colSpan={6}>
                        <pre className="activity-detail-json">{JSON.stringify(a.detail, null, 2)}</pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {wipeConfirm && (
        <div className="admin-confirm-overlay" data-testid="wipe-confirm-overlay">
          <div className="admin-confirm-card">
            <h3>
              <AlertTriangle size={20} /> Wipe all activity?
            </h3>
            <p>
              This will permanently delete <strong>every event</strong> in the activity log
              ({total} events). Buyer records are unaffected. This cannot be undone.
            </p>
            <div className="admin-confirm-actions">
              <button className="admin-btn" onClick={() => setWipeConfirm(false)} data-testid="wipe-cancel">
                Cancel
              </button>
              <button className="admin-btn is-danger" onClick={wipeAll} data-testid="wipe-confirm">
                Yes, wipe everything
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className={`admin-toast is-${toast.kind}`} data-testid="admin-toast" role="status">
          {toast.msg}
        </div>
      )}
    </div>
  );
}
