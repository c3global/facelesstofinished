import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, Plus, Trash2, Download, RefreshCw, X, FileUp, HelpCircle } from "lucide-react";
import { apiClient } from "../../App";

const ENTITLEMENTS = ["base", "shorts", "studio"];
const NETLIFY_BUYERS_URL = "https://faceless48.c3global.co/api/admin-buyers";

// Minimal RFC-4180 CSV parser. Handles quoted fields with commas + escaped
// double-quotes ("a,b" → a,b ; "say ""hi""" → say "hi"). Returns array of
// arrays. Empty trailing rows are dropped.
function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field); field = "";
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = "";
      if (row.some((v) => v.length > 0)) rows.push(row);
      row = [];
    } else {
      field += c;
    }
  }
  if (field.length || row.length) {
    row.push(field);
    if (row.some((v) => v.length > 0)) rows.push(row);
  }
  return rows;
}

// Map a parsed CSV (array of arrays, first row = header) into BuyerImportRow[].
function csvToBuyers(text) {
  const rows = parseCSV(text);
  if (rows.length < 2) return { buyers: [], errors: ["CSV is empty or has no data rows"] };
  const header = rows[0].map((h) => h.trim().replace(/^\uFEFF/, ""));  // strip BOM
  const idx = (name) => header.findIndex((h) => h.toLowerCase() === name.toLowerCase());

  const emailIdx = idx("email");
  if (emailIdx === -1) {
    return {
      buyers: [],
      errors: ["CSV must include an 'email' column. Other columns are optional."],
    };
  }

  const splitList = (s) => (s || "").split(/[,;|]/).map((x) => x.trim()).filter(Boolean);
  const parseNum = (s) => {
    const n = parseInt((s || "0").replace(/[^0-9-]/g, ""), 10);
    return Number.isFinite(n) ? n : 0;
  };
  const parseDate = (s) => {
    if (!s || !s.trim()) return null;
    const d = new Date(s.trim());
    return isNaN(d.getTime()) ? s.trim() : d.toISOString();
  };

  const cell = (row, col) => {
    const i = idx(col);
    return i === -1 ? "" : (row[i] || "").trim();
  };

  const buyers = rows.slice(1).map((row) => ({
    email: cell(row, "email").toLowerCase(),
    entitlements: splitList(cell(row, "entitlements")),
    totalSpendCents: parseNum(cell(row, "totalSpendCents") || cell(row, "spend") || cell(row, "total_spend_cents")),
    seenOrderIds: splitList(cell(row, "seenOrderIds") || cell(row, "order_ids")),
    orderId: cell(row, "orderId") || cell(row, "order_id") || null,
    addedAt: parseDate(cell(row, "addedAt") || cell(row, "added_at") || cell(row, "createdAt") || cell(row, "created_at")),
    lastLoginAt: parseDate(cell(row, "lastLoginAt") || cell(row, "last_login_at") || cell(row, "lastLogin")),
    loginCount: parseNum(cell(row, "loginCount") || cell(row, "login_count")),
    scriptCount: parseNum(cell(row, "scriptCount") || cell(row, "script_count")),
    shortsCount: parseNum(cell(row, "shortsCount") || cell(row, "shorts_count")),
    firstUseAt: parseDate(cell(row, "firstUseAt") || cell(row, "first_use_at")),
    source: cell(row, "source") || "csv-import",
    event: cell(row, "event") || null,
  }));
  return { buyers, errors: [] };
}

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
  const [csvHelp, setCsvHelp] = useState(false);
  const csvFileRef = useRef(null);

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

  const importFromCSV = async (file) => {
    if (!file || importing) return;
    setImporting(true);
    try {
      const text = await file.text();
      const { buyers, errors } = csvToBuyers(text);
      if (errors.length) {
        showToast(errors[0], "err");
        return;
      }
      if (buyers.length === 0) {
        showToast("No rows found in CSV", "err");
        return;
      }
      const r = await apiClient.post("/admin/buyers/import", { buyers });
      const { imported, merged, skipped, errors: rowErrors } = r.data;
      showToast(
        `Import done — ${imported} new · ${merged} merged · ${skipped} skipped` +
          (rowErrors?.length ? ` · ${rowErrors.length} errors` : ""),
      );
      load();
    } catch (e) {
      showToast(e?.response?.data?.detail || e?.message || "CSV import failed", "err");
    } finally {
      setImporting(false);
      if (csvFileRef.current) csvFileRef.current.value = "";
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

        {/* Hidden file input drives the CSV import button */}
        <input
          ref={csvFileRef}
          type="file"
          accept=".csv,text/csv"
          style={{ display: "none" }}
          onChange={(e) => importFromCSV(e.target.files?.[0])}
          data-testid="buyers-csv-input"
        />
        <button
          className="admin-btn is-primary"
          onClick={() => csvFileRef.current?.click()}
          disabled={importing}
          data-testid="buyers-import-csv"
          title="Upload a CSV exported from Netlify, GHL, Pinball, or anywhere else"
        >
          <FileUp size={13} /> {importing ? "Importing…" : "Import CSV"}
        </button>
        <button
          className="admin-btn"
          onClick={() => setCsvHelp(true)}
          aria-label="CSV format help"
          data-testid="buyers-csv-help"
          title="Show CSV format help"
        >
          <HelpCircle size={13} />
        </button>
        <button
          className="admin-btn"
          onClick={importFromNetlify}
          disabled={importing}
          data-testid="buyers-import-netlify"
          title="Same-origin fetch to Netlify's /api/admin-buyers using your existing session cookie, then POST to /api/admin/buyers/import"
        >
          <Download size={13} /> Sync from Netlify
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
              <tr><td colSpan={7} className="admin-empty">No buyers found. Click <strong>Import CSV</strong> to seed the list.</td></tr>
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

      {csvHelp && (
        <div className="admin-confirm-overlay" data-testid="csv-help-overlay" onClick={() => setCsvHelp(false)}>
          <div className="admin-confirm-card csv-help-card" onClick={(e) => e.stopPropagation()}>
            <h3><HelpCircle size={20} /> CSV format</h3>
            <p>
              First row is the header. Only <code>email</code> is required — every other column is optional.
              Unknown columns are ignored, so you can drop in exports from Netlify, GHL, or Pinball as-is.
            </p>
            <pre className="csv-help-example">{`email,entitlements,totalSpendCents,seenOrderIds,addedAt,lastLoginAt,loginCount
alex@example.com,"base,studio",29700,"po_1,po_2",2026-01-01,2026-02-15,12
jamie@example.com,base,700,po_3,2026-02-10,2026-02-18,4
priya@example.com,"base,shorts",4400,,,,`}</pre>
            <ul className="csv-help-notes">
              <li><strong>entitlements</strong> &amp; <strong>seenOrderIds</strong>: comma/semicolon/pipe-separated inside quotes.</li>
              <li><strong>Counter columns</strong> (totalSpendCents, loginCount, scriptCount, shortsCount): integers; existing values are kept if higher.</li>
              <li><strong>Date columns</strong> (addedAt, lastLoginAt, firstUseAt): any parseable date; leave blank to preserve existing.</li>
              <li>Existing buyers are <strong>upserted</strong>: entitlements + order IDs are unioned, counters take the max, addedAt keeps the earliest, lastLoginAt keeps the latest. Never null-overwrites.</li>
              <li>Bad rows (invalid email, etc.) are skipped and reported back in the result toast.</li>
            </ul>
            <div className="admin-confirm-actions">
              <button className="admin-btn is-primary" onClick={() => setCsvHelp(false)} data-testid="csv-help-close">
                Got it
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
