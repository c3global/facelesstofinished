import React from "react";
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

export default function ScriptHistoryList({ history, onOpen, onDelete }) {
  return (
    <div className="history-block" data-testid="scripts-history">
      <div className="history-head">Recent scripts</div>
      {history.length === 0 ? (
        <div className="history-empty">No scripts yet. Generate one above.</div>
      ) : (
        <div className="history-list">
          {history
            .filter((s) => s.status !== "running")
            .map((s) => (
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
                    {s.mode === "long" ? "Long" : "Short"}
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
