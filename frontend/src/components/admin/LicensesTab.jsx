import React, { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Plus, X, Ban, Search } from "lucide-react";
import { apiClient } from "../../App";

/**
 * Admin → Licenses tab. Lets the operator:
 *   • Bulk-create redemption codes by pasting a CSV blob (or one code per
 *     line if they only have 1-2 codes from a small partner deal).
 *   • Filter the existing inventory by status / tier / source / batch.
 *   • Void leaked / refunded codes.
 *
 * Bulk-create accepts either:
 *   code,tier
 *   F48-A1B2-C3D4,t1
 *   F48-E5F6-G7H8,t3
 * OR a list of "CODE,t1" lines without a header (we auto-detect).
 *
 * The "Source" field defaults to "appsumo" since that's the v1 launch
 * channel, but partners / agencies / beta groups can be uploaded with a
 * custom source string for downstream reporting.
 */
const STATUS_OPTIONS = ["", "available", "redeemed", "void"];
const TIER_OPTIONS   = ["", "t1", "t2", "t3"];

function fmtDate(s) {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return s; }
}

export default function LicensesTab() {
  const [items, setItems] = useState([]);
  const [totals, setTotals] = useState({ available: 0, redeemed: 0, void: 0 });
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [q, setQ] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [createSource, setCreateSource] = useState("appsumo");
  const [createBatchId, setCreateBatchId] = useState("");
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState("");

  const flashToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(""), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter) params.status = statusFilter;
      if (tierFilter) params.tier = tierFilter;
      if (q.trim()) params.q = q.trim();
      const r = await apiClient.get("/admin/licenses", { params });
      setItems(r.data?.items || []);
      setTotals(r.data?.totals || { available: 0, redeemed: 0, void: 0 });
    } catch (e) {
      flashToast(e?.response?.data?.detail || "Failed to load licenses");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, tierFilter, q]);

  useEffect(() => { load(); }, [load]);

  const createCodes = async () => {
    const text = csvText.trim();
    if (!text || creating) return;
    setCreating(true);
    try {
      // Auto-detect: if text has a "code,tier" header we send as CSV;
      // otherwise we send a parsed codes[] array of {code, tier}.
      const firstLine = text.split(/\r?\n/, 1)[0] || "";
      const hasHeader = /code/i.test(firstLine) && /tier/i.test(firstLine);
      const body = hasHeader
        ? { csv: text, source: createSource.trim() || "appsumo", batch_id: createBatchId.trim() || undefined }
        : {
            codes: text.split(/\r?\n/).map((line) => {
              const [code, tier, ...rest] = line.split(",").map((s) => s.trim());
              return code ? { code, tier: tier || "t1", notes: rest.join(",") || undefined } : null;
            }).filter(Boolean),
            source: createSource.trim() || "appsumo",
            batch_id: createBatchId.trim() || undefined,
          };
      const r = await apiClient.post("/admin/licenses/bulk-create", body);
      const { created, skipped_duplicates, invalid, batch_id } = r.data;
      flashToast(
        `Imported ${created} · skipped ${skipped_duplicates} · invalid ${invalid?.length || 0} · batch ${batch_id || "—"}`
      );
      setCsvText("");
      setShowCreate(false);
      load();
    } catch (e) {
      flashToast(e?.response?.data?.detail || "Bulk create failed");
    } finally {
      setCreating(false);
    }
  };

  const voidCode = async (code) => {
    if (!window.confirm(`Void code "${code}"? This can't be undone.`)) return;
    try {
      await apiClient.post(`/admin/licenses/${encodeURIComponent(code)}/void`);
      flashToast(`Voided ${code}`);
      load();
    } catch (e) {
      flashToast(e?.response?.data?.detail || "Void failed");
    }
  };

  const totalAll = useMemo(
    () => (totals.available || 0) + (totals.redeemed || 0) + (totals.void || 0),
    [totals]
  );

  return (
    <div className="admin-section" data-testid="licenses-tab">
      <div className="admin-toolbar">
        <div className="admin-search">
          <Search size={14} />
          <input
            type="text"
            placeholder="Search by code or redeemer email…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            data-testid="licenses-search"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="admin-select"
          data-testid="licenses-status-filter"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s ? s : "All statuses"}</option>
          ))}
        </select>
        <select
          value={tierFilter}
          onChange={(e) => setTierFilter(e.target.value)}
          className="admin-select"
          data-testid="licenses-tier-filter"
        >
          {TIER_OPTIONS.map((t) => (
            <option key={t} value={t}>{t ? t.toUpperCase() : "All tiers"}</option>
          ))}
        </select>
        <button className="admin-btn" onClick={load} data-testid="licenses-refresh">
          <RefreshCw size={13} /> Refresh
        </button>
        <button
          className="admin-btn is-primary"
          onClick={() => setShowCreate(true)}
          data-testid="licenses-create-btn"
        >
          <Plus size={13} /> Bulk create
        </button>
        <span className="admin-meta" data-testid="licenses-totals">
          {totalAll} codes · {totals.redeemed} redeemed · {totals.available} available · {totals.void} void
        </span>
      </div>

      {showCreate && (
        <div className="admin-create-panel" data-testid="licenses-create-panel">
          <div className="admin-create-head">
            <h4>Bulk-create codes</h4>
            <button
              type="button"
              className="admin-icon-btn"
              onClick={() => setShowCreate(false)}
              aria-label="Close"
              data-testid="licenses-create-close"
            >
              <X size={14} />
            </button>
          </div>
          <p className="admin-create-hint">
            Paste one of:
            <br />
            • CSV with header — <code>code,tier[,notes]</code>
            <br />
            • Comma-separated lines — <code>F48-AAAA-BBBB,t1</code> (one per line)
            <br />
            Tier must be <code>t1</code> / <code>t2</code> / <code>t3</code>.
            Duplicate codes are skipped silently.
          </p>
          <textarea
            rows={8}
            className="admin-textarea"
            placeholder={"code,tier\nF48-AAAA-BBBB,t2\nF48-CCCC-DDDD,t3"}
            // NOTE: t2 = Pro ($179), t3 = Pro Plus ($349), t1 = Starter ($49).
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
            data-testid="licenses-csv-input"
          />
          <div className="admin-create-row">
            <label>
              <span className="admin-create-label">Source</span>
              <input
                type="text"
                value={createSource}
                onChange={(e) => setCreateSource(e.target.value)}
                placeholder="appsumo"
                data-testid="licenses-source-input"
              />
            </label>
            <label>
              <span className="admin-create-label">Batch id (optional)</span>
              <input
                type="text"
                value={createBatchId}
                onChange={(e) => setCreateBatchId(e.target.value)}
                placeholder="auto-generated if blank"
                data-testid="licenses-batch-input"
              />
            </label>
            <button
              type="button"
              className="admin-btn is-primary"
              onClick={createCodes}
              disabled={!csvText.trim() || creating}
              data-testid="licenses-create-submit"
            >
              {creating ? "Importing…" : "Import codes"}
            </button>
          </div>
        </div>
      )}

      <div className="admin-table-wrap">
        <table className="admin-table" data-testid="licenses-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Tier</th>
              <th>Source</th>
              <th>Status</th>
              <th>Batch</th>
              <th>Redeemed by</th>
              <th>Redeemed at</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={9} className="admin-empty">Loading…</td></tr>}
            {!loading && items.length === 0 && (
              <tr><td colSpan={9} className="admin-empty">No codes yet. Hit "Bulk create" to add some.</td></tr>
            )}
            {!loading && items.map((row) => (
              <tr key={row.code} data-testid={`licenses-row-${row.code}`}>
                <td className="admin-td-code">{row.code}</td>
                <td><span className={`ent-chip ent-chip-${row.tier || "t1"}`}>{(row.tier || "—").toUpperCase()}</span></td>
                <td>{row.source || "—"}</td>
                <td><span className={`licenses-status licenses-status-${row.status}`}>{row.status}</span></td>
                <td>{row.batch_id || "—"}</td>
                <td>{row.redeemed_by || "—"}</td>
                <td>{fmtDate(row.redeemed_at)}</td>
                <td>{fmtDate(row.created_at)}</td>
                <td>
                  {row.status !== "void" && (
                    <button
                      className="admin-icon-btn"
                      onClick={() => voidCode(row.code)}
                      data-testid={`licenses-void-${row.code}`}
                      title="Void this code"
                    >
                      <Ban size={13} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {toast && (
        <div className="admin-toast" data-testid="admin-toast" role="status">{toast}</div>
      )}
    </div>
  );
}
