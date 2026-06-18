import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw, Repeat } from "lucide-react";
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
  const [toast, setToast] = useState(null);

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
    } catch (e) {
      showToast(e?.response?.data?.detail || "Failed to load activity", "err");
    } finally {
      setLoading(false);
    }
  }, [filterType, filterEmail, dateFrom, dateTo, showToast]);

  useEffect(() => {
    load();
  }, [load]);

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
        <span className="admin-meta" data-testid="activity-total">{total} events</span>
      </div>

      <div className="admin-table-wrap">
        <table className="admin-table" data-testid="activity-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Type</th>
              <th>Email</th>
              <th>Detail</th>
              <th className="admin-th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={5} className="admin-empty">Loading…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={5} className="admin-empty">No activity matches these filters.</td></tr>
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
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="activity-detail-row" data-testid={`activity-detail-row-${a.id}`}>
                      <td colSpan={5}>
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

      {toast && (
        <div className={`admin-toast is-${toast.kind}`} data-testid="admin-toast" role="status">
          {toast.msg}
        </div>
      )}
    </div>
  );
}
