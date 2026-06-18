import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Search, Plus, Trash2, Download, RefreshCw, X } from "lucide-react";
import { apiClient } from "../../App";

const ENTITLEMENTS = ["base", "shorts", "studio"];
const NETLIFY_BUYERS_URL = "https://faceless48.c3global.co/api/admin-buyers";

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

export default function BuyersTab() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [entitlementFilter, setEntitlementFilter] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [toast, setToast] = useState(null);
  const [granting, setGranting] = useState(null); // buyer email currently choosing entitlement
  const [importing, setImporting] = useState(false);

  const showToast = useCallback((msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (q.trim()) params.q = q.trim();
      if (entitlementFilter) params.entitlement = entitlementFilter;
      const r = await apiClient.get("/admin/buyers", { params });
      setItems(r.data.items || []);
      setTotal(r.data.total || 0);
    } catch (e) {
      showToast(e?.response?.data?.detail || "Failed to load buyers", "err");
    } finally {
      setLoading(false);
    }
  }, [q, entitlementFilter, showToast]);

  useEffect(() => {
    load();
  }, [load]);

  const allSelected = useMemo(
    () => items.length > 0 && items.every((b) => selected.has(b.email)),
    [items, selected],
  );
  const toggleAll = () => {
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(items.map((b) => b.email)));
  };
  const toggleOne = (email) => {
    const next = new Set(selected);
    if (next.has(email)) next.delete(email);
    else next.add(email);
    setSelected(next);
  };

  const grant = async (email, ent) => {
    // Optimistic update
    const prev = items;
    setItems((cur) =>
      cur.map((b) =>
        b.email === email
          ? { ...b, entitlements: Array.from(new Set([...(b.entitlements || []), ent])) }
          : b,
      ),
    );
    setGranting(null);
    try {
      await apiClient.patch(`/admin/buyers/${encodeURIComponent(email)}/grant`, { entitlement: ent });
      showToast(`Granted ${ent} to ${email}`);
    } catch (e) {
      setItems(prev);
      showToast(e?.response?.data?.detail || "Grant failed", "err");
    }
  };

  const revoke = async (email, ent) => {
    const prev = items;
    setItems((cur) =>
      cur.map((b) =>
        b.email === email
          ? { ...b, entitlements: (b.entitlements || []).filter((x) => x !== ent) }
          : b,
      ),
    );
    try {
      await apiClient.patch(`/admin/buyers/${encodeURIComponent(email)}/revoke`, { entitlement: ent });
      showToast(`Revoked ${ent} from ${email}`);
    } catch (e) {
      setItems(prev);
      showToast(e?.response?.data?.detail || "Revoke failed", "err");
    }
  };

  const deleteOne = async (email) => {
    if (!window.confirm(`Delete buyer ${email}? This cannot be undone.`)) return;
    const prev = items;
    setItems((cur) => cur.filter((b) => b.email !== email));
    try {
      await apiClient.delete(`/admin/buyers/${encodeURIComponent(email)}`);
      showToast(`Deleted ${email}`);
    } catch (e) {
      setItems(prev);
      showToast(e?.response?.data?.detail || "Delete failed", "err");
    }
  };

  const bulkDelete = async () => {
    const emails = Array.from(selected);
    if (emails.length === 0) return;
    if (!window.confirm(`Delete ${emails.length} buyer(s)? This cannot be undone.`)) return;
    const prev = items;
    setItems((cur) => cur.filter((b) => !selected.has(b.email)));
    setSelected(new Set());
    try {
      const r = await apiClient.post("/admin/buyers/bulk-delete", { emails });
      showToast(`Deleted ${r.data.deleted} buyers`);
    } catch (e) {
      setItems(prev);
      showToast(e?.response?.data?.detail || "Bulk delete failed", "err");
    }
  };

  const importFromNetlify = async () => {
    if (importing) return;
    setImporting(true);
    try {
      // Step 1: same-origin fetch to Netlify using the admin's cookie session.
      // Works when this UI is served from faceless48.c3global.co/studio behind
      // the reverse-proxy; during dev/preview this will fail CORS unless the
      // user opens the production URL. Surface the failure clearly.
      const resp = await fetch(NETLIFY_BUYERS_URL, { credentials: "include" });
      if (!resp.ok) throw new Error(`Netlify returned ${resp.status}`);
      const data = await resp.json();
      const buyers = Array.isArray(data) ? data : data.buyers || data.items || [];
      if (!Array.isArray(buyers) || buyers.length === 0) {
        showToast("No buyers found in Netlify response", "err");
        return;
      }
      // Step 2: POST batch to our import endpoint.
      const r = await apiClient.post("/admin/buyers/import", { buyers });
      const { imported, merged, skipped, errors } = r.data;
      showToast(
        `Import done — ${imported} new · ${merged} merged · ${skipped} skipped` +
          (errors?.length ? ` · ${errors.length} errors` : ""),
      );
      load();
    } catch (e) {
      const msg = e?.message?.includes("Failed to fetch")
        ? "Couldn't reach Netlify. Open this page on faceless48.c3global.co/studio so cookies are same-origin."
        : e?.message || "Import failed";
      showToast(msg, "err");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="admin-section" data-testid="buyers-tab">
      <div className="admin-toolbar">
        <div className="admin-search">
          <Search size={14} />
          <input
            type="text"
            placeholder="Search by email…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            data-testid="buyers-search"
          />
        </div>
        <select
          className="admin-select"
          value={entitlementFilter}
          onChange={(e) => setEntitlementFilter(e.target.value)}
          data-testid="buyers-filter-entitlement"
        >
          <option value="">All entitlements</option>
          {ENTITLEMENTS.map((e) => (
            <option key={e} value={e}>{e}</option>
          ))}
        </select>
        <button className="admin-btn" onClick={load} data-testid="buyers-refresh">
          <RefreshCw size={13} /> Refresh
        </button>
        <button
          className="admin-btn is-primary"
          onClick={importFromNetlify}
          disabled={importing}
          data-testid="buyers-import"
          title="Fetches /api/admin-buyers from Netlify (same-origin via reverse proxy) and POSTs the JSON to /api/admin/buyers/import"
        >
          <Download size={13} /> {importing ? "Importing…" : "Import from Netlify"}
        </button>
        {selected.size > 0 && (
          <button
            className="admin-btn is-danger"
            onClick={bulkDelete}
            data-testid="buyers-bulk-delete"
          >
            <Trash2 size={13} /> Delete {selected.size}
          </button>
        )}
        <span className="admin-meta" data-testid="buyers-total">{total} total</span>
      </div>

      <div className="admin-table-wrap">
        <table className="admin-table" data-testid="buyers-table">
          <thead>
            <tr>
              <th className="admin-th-checkbox">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label="Select all"
                  data-testid="buyers-select-all"
                />
              </th>
              <th>Email</th>
              <th>Entitlements</th>
              <th>Spend</th>
              <th>Last login</th>
              <th>Added</th>
              <th className="admin-th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7} className="admin-empty">Loading…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="admin-empty">No buyers found. Click <strong>Import from Netlify</strong> to seed the list.</td></tr>
            )}
            {!loading && items.map((b) => (
              <tr key={b.email} data-testid={`buyer-row-${b.email}`}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(b.email)}
                    onChange={() => toggleOne(b.email)}
                    aria-label={`Select ${b.email}`}
                    data-testid={`buyer-select-${b.email}`}
                  />
                </td>
                <td className="admin-td-email">{b.email}</td>
                <td>
                  <div className="ent-chips">
                    {(b.entitlements || []).map((ent) => (
                      <span key={ent} className={`ent-chip ent-chip-${ent}`}>
                        {ent}
                        <button
                          className="ent-chip-x"
                          onClick={() => revoke(b.email, ent)}
                          aria-label={`Revoke ${ent}`}
                          data-testid={`revoke-${b.email}-${ent}`}
                        >
                          <X size={10} />
                        </button>
                      </span>
                    ))}
                    {granting === b.email ? (
                      <div className="ent-grant-pop">
                        {ENTITLEMENTS.filter((e) => !(b.entitlements || []).includes(e)).map((e) => (
                          <button
                            key={e}
                            className="ent-grant-opt"
                            onClick={() => grant(b.email, e)}
                            data-testid={`grant-${b.email}-${e}`}
                          >
                            + {e}
                          </button>
                        ))}
                        <button className="ent-grant-cancel" onClick={() => setGranting(null)}>
                          <X size={10} />
                        </button>
                      </div>
                    ) : (
                      (b.entitlements || []).length < ENTITLEMENTS.length && (
                        <button
                          className="ent-grant-btn"
                          onClick={() => setGranting(b.email)}
                          data-testid={`grant-open-${b.email}`}
                        >
                          <Plus size={10} /> Grant
                        </button>
                      )
                    )}
                  </div>
                </td>
                <td>{fmtCents(b.totalSpendCents)}</td>
                <td>{fmtDate(b.lastLoginAt)}</td>
                <td>{fmtDate(b.addedAt)}</td>
                <td>
                  <button
                    className="admin-icon-btn"
                    onClick={() => deleteOne(b.email)}
                    aria-label="Delete buyer"
                    data-testid={`delete-${b.email}`}
                  >
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
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
