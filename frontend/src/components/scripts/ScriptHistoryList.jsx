import React, { useState } from "react";
import { FileText, Trash2 } from "lucide-react";

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

// Available filter buckets. "auto" follows the page's current mode
// (the default the user agreed to) — switching to Shorts hides longs,
// switching to Long shows everything. The explicit pills let the user
// override that default without leaving the page.
const FILTERS = [
  { id: "auto", label: "Current" },
  { id: "all", label: "All" },
  { id: "long", label: "Long" },
  { id: "shorts", label: "Shorts" },
  { id: "sprint", label: "Sprint" },
];

function applyFilter(rows, filter, currentMode) {
  if (filter === "all") return rows;
  if (filter === "long") return rows.filter((s) => s.mode === "long");
  if (filter === "shorts") return rows.filter((s) => s.mode === "shorts");
  if (filter === "sprint") return rows.filter((s) => s.mode === "sprint");
  // "auto" — mirrors the current page mode
  if (currentMode === "shorts") {
    return rows.filter((s) => s.mode === "shorts" || s.mode === "sprint");
  }
  return rows;
}

export default function ScriptHistoryList({ history, currentMode, onOpen, onDelete }) {
  const [filter, setFilter] = useState("auto");

  const rowsByMode = React.useMemo(
    () => history.filter((s) => s.status !== "running"),
    [history]
  );
  const filtered = React.useMemo(
    () => applyFilter(rowsByMode, filter, currentMode),
    [rowsByMode, filter, currentMode]
  );

  return (
    <div className="history-block" data-testid="scripts-history">
      <div className="history-head-row">
        <div className="history-head">Recent scripts</div>
        <div
          className="history-filter"
          role="tablist"
          aria-label="Filter recent scripts"
          data-testid="scripts-history-filter"
        >
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={filter === f.id}
              className={`history-filter-pill ${filter === f.id ? "is-active" : ""}`}
              data-testid={`scripts-history-filter-${f.id}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {filtered.length === 0 ? (
        <div className="history-empty">No scripts yet. Generate one above.</div>
      ) : (
        <div className="history-list">
          {filtered.map((s) => (
            <div
              className="history-row"
              key={s.id}
              data-testid={`scripts-history-row-${s.id}`}
            >
              <div
                className="history-meta"
                style={{ minWidth: 0, flex: 1 }}
              >
                <span
                  className={`history-chip is-${s.mode === "long" ? "avatar" : "faceless"}`}
                >
                  {s.mode === "long" ? "Long" : s.mode === "sprint" ? "Sprint" : "Short"}
                </span>
                <span
                  style={{
                    color: "var(--text)",
                    fontSize: 13,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.topic}
                </span>
                <span className="history-date">{fmtDate(s.created_at)}</span>
              </div>
              <div className="history-actions">
                <button
                  className="icon-btn"
                  onClick={() => onOpen(s.id)}
                  data-testid={`scripts-history-open-${s.id}`}
                  aria-label="Open"
                >
                  <FileText size={14} />
                </button>
                <button
                  className="icon-btn is-danger"
                  onClick={() => onDelete(s.id)}
                  data-testid={`scripts-history-delete-${s.id}`}
                  aria-label="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
