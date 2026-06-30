import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft, CheckCircle2, Sparkles, ListChecks, Lightbulb,
  Pencil, Trash2, Plus, Save, X, ArrowUp, ArrowDown,
} from "lucide-react";
import { useAuth, apiClient } from "../App";

// Public roadmap page at /roadmap.
//
// READ path: GET /api/roadmap (public, no auth). Backend seeds defaults
// the first time the collection is empty so the page never renders blank.
//
// ADMIN path: when the signed-in user has `isAdmin` true (Charity), each
// card sprouts edit / delete buttons + each column gets an "Add item"
// button at the bottom. Every write hits an admin-gated endpoint
// (require_admin server-side, not just UI hiding).
//
// Layout mirrors the existing in-app pages — hero block + 4 columns of
// cards. Theme tokens (--bg, --surface, --text, --muted, --accent,
// --warning, --border) auto-switch with the dark/light toggle.

const COLUMN_ICONS = {
  shipped: CheckCircle2,
  inProgress: Sparkles,
  planned: ListChecks,
  considering: Lightbulb,
};

const COLUMN_OPTIONS = [
  { key: "shipped",     label: "Shipped" },
  { key: "inProgress",  label: "In Progress" },
  { key: "planned",     label: "Planned" },
  { key: "considering", label: "Considering" },
];

// Tag presets shown in the admin tag-picker. Charity can still type a
// custom tag — these are just shortcuts for the recurring ones.
const TAG_PRESETS = ["", "Top request", "P0", "This week", "AppSumo", "Pro Plus"];

function tagDataAttr(tag) {
  return (tag || "").toLowerCase().replace(/\s+/g, "-");
}

function ItemView({ item, isAdmin, onEdit, onDelete, onMove, isFirst, isLast }) {
  return (
    <li
      className="roadmap-item"
      data-testid={`roadmap-item-${item.column}-${item.id}`}
    >
      <div className="roadmap-item-head">
        <h3 className="roadmap-item-title">{item.title}</h3>
        {item.tag && (
          <span className="roadmap-item-tag" data-tag={tagDataAttr(item.tag)}>
            {item.tag}
          </span>
        )}
      </div>
      <p className="roadmap-item-blurb">{item.blurb}</p>
      {isAdmin && (
        <div className="roadmap-item-admin">
          <button
            type="button"
            className="roadmap-icon-btn"
            data-testid={`roadmap-move-up-${item.id}`}
            disabled={isFirst}
            onClick={() => onMove(item, -1)}
            aria-label="Move up"
            title="Move up"
          >
            <ArrowUp size={13} />
          </button>
          <button
            type="button"
            className="roadmap-icon-btn"
            data-testid={`roadmap-move-down-${item.id}`}
            disabled={isLast}
            onClick={() => onMove(item, +1)}
            aria-label="Move down"
            title="Move down"
          >
            <ArrowDown size={13} />
          </button>
          <button
            type="button"
            className="roadmap-icon-btn"
            data-testid={`roadmap-edit-${item.id}`}
            onClick={() => onEdit(item)}
            aria-label="Edit"
            title="Edit"
          >
            <Pencil size={13} />
          </button>
          <button
            type="button"
            className="roadmap-icon-btn roadmap-icon-btn-danger"
            data-testid={`roadmap-delete-${item.id}`}
            onClick={() => onDelete(item)}
            aria-label="Delete"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </div>
      )}
    </li>
  );
}

function ItemEditor({ initial, onSave, onCancel }) {
  // Inline form used for BOTH "new item" + "edit existing". `initial`
  // already has the right column pre-filled when adding from a column
  // footer button; admin can still switch columns via the dropdown.
  const [column, setColumn] = useState(initial.column || "planned");
  const [title, setTitle]   = useState(initial.title || "");
  const [blurb, setBlurb]   = useState(initial.blurb || "");
  const [tag, setTag]       = useState(initial.tag || "");
  const [saving, setSaving] = useState(false);
  const [err, setErr]       = useState("");
  const isNew = !initial.id;

  const submit = async (e) => {
    e.preventDefault();
    if (!title.trim() || !blurb.trim() || saving) return;
    setErr("");
    setSaving(true);
    try {
      await onSave({
        column,
        title: title.trim(),
        blurb: blurb.trim(),
        tag: tag.trim(),
      });
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not save. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="roadmap-item roadmap-item-editor" data-testid="roadmap-item-editor">
      <form onSubmit={submit} className="roadmap-editor-form">
        <div className="roadmap-editor-row">
          <label className="roadmap-editor-label">Column</label>
          <select
            className="roadmap-editor-select"
            data-testid="roadmap-editor-column"
            value={column}
            onChange={(e) => setColumn(e.target.value)}
          >
            {COLUMN_OPTIONS.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        </div>
        <div className="roadmap-editor-row">
          <label className="roadmap-editor-label">Title</label>
          <input
            type="text"
            className="roadmap-editor-input"
            data-testid="roadmap-editor-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={120}
            placeholder="Short, benefit-led title"
            required
          />
        </div>
        <div className="roadmap-editor-row">
          <label className="roadmap-editor-label">Blurb</label>
          <textarea
            className="roadmap-editor-textarea"
            data-testid="roadmap-editor-blurb"
            value={blurb}
            onChange={(e) => setBlurb(e.target.value)}
            maxLength={600}
            rows={3}
            placeholder="One sentence describing the buyer benefit. No internal jargon."
            required
          />
        </div>
        <div className="roadmap-editor-row">
          <label className="roadmap-editor-label">Tag (optional)</label>
          <div className="roadmap-editor-tag-row">
            <input
              type="text"
              className="roadmap-editor-input roadmap-editor-tag-input"
              data-testid="roadmap-editor-tag"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              maxLength={40}
              placeholder="e.g. Top request"
            />
            <div className="roadmap-editor-tag-presets">
              {TAG_PRESETS.filter(Boolean).map((p) => (
                <button
                  key={p}
                  type="button"
                  className="roadmap-tag-preset"
                  onClick={() => setTag(p)}
                  data-testid={`roadmap-tag-preset-${tagDataAttr(p)}`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>
        {err && <p className="roadmap-editor-error" data-testid="roadmap-editor-error">{err}</p>}
        <div className="roadmap-editor-actions">
          <button
            type="button"
            className="roadmap-btn roadmap-btn-ghost"
            onClick={onCancel}
            data-testid="roadmap-editor-cancel"
          >
            <X size={13} /> Cancel
          </button>
          <button
            type="submit"
            className="roadmap-btn roadmap-btn-primary"
            disabled={saving || !title.trim() || !blurb.trim()}
            data-testid="roadmap-editor-save"
          >
            <Save size={13} /> {saving ? "Saving…" : isNew ? "Add item" : "Save"}
          </button>
        </div>
      </form>
    </li>
  );
}

function RoadmapColumn({
  columnKey, column, isAdmin,
  editingId, addingInColumn,
  onStartEdit, onCancel, onSave, onDelete, onMove, onStartAdd,
}) {
  const Icon = COLUMN_ICONS[columnKey] || ListChecks;
  const items = column.items || [];
  return (
    <section
      className={`roadmap-column roadmap-column-${columnKey}`}
      data-testid={`roadmap-column-${columnKey}`}
    >
      <header className="roadmap-column-head">
        <Icon size={18} strokeWidth={2} aria-hidden />
        <h2 className="roadmap-column-title">{column.label}</h2>
        <span className="roadmap-column-count">{items.length}</span>
      </header>
      {column.note && <p className="roadmap-column-note">{column.note}</p>}
      <ul className="roadmap-list">
        {items.map((item, idx) => (
          editingId === item.id ? (
            <ItemEditor
              key={item.id}
              initial={item}
              onSave={(patch) => onSave({ ...item, ...patch })}
              onCancel={onCancel}
            />
          ) : (
            <ItemView
              key={item.id}
              item={{ ...item, column: columnKey }}
              isAdmin={isAdmin}
              isFirst={idx === 0}
              isLast={idx === items.length - 1}
              onEdit={onStartEdit}
              onDelete={onDelete}
              onMove={onMove}
            />
          )
        ))}
        {addingInColumn === columnKey && (
          <ItemEditor
            initial={{ column: columnKey }}
            onSave={(patch) => onSave({ ...patch })}
            onCancel={onCancel}
          />
        )}
      </ul>
      {isAdmin && addingInColumn !== columnKey && (
        <button
          type="button"
          className="roadmap-add-btn"
          data-testid={`roadmap-add-${columnKey}`}
          onClick={() => onStartAdd(columnKey)}
        >
          <Plus size={13} /> Add item
        </button>
      )}
    </section>
  );
}

export default function Roadmap() {
  const { user } = useAuth();
  const isAdmin = !!(user && user.isAdmin);
  const [columns, setColumns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  // Admin-edit state. editingId = uuid currently in inline-edit mode.
  // addingInColumn = column key currently showing the "new item" editor.
  const [editingId, setEditingId] = useState(null);
  const [addingInColumn, setAddingInColumn] = useState(null);

  const load = async () => {
    setError("");
    try {
      const r = await apiClient.get("/roadmap");
      setColumns(r.data?.columns || []);
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not load roadmap.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const cancel = () => { setEditingId(null); setAddingInColumn(null); };

  const startEdit = (item) => { setAddingInColumn(null); setEditingId(item.id); };
  const startAdd  = (col)  => { setEditingId(null);     setAddingInColumn(col); };

  const save = async (patch) => {
    if (patch.id) {
      // Edit existing
      await apiClient.patch(`/admin/roadmap/items/${patch.id}`, {
        column: patch.column,
        title:  patch.title,
        blurb:  patch.blurb,
        tag:    patch.tag ?? "",
      });
    } else {
      // Create new
      await apiClient.post("/admin/roadmap/items", {
        column: patch.column,
        title:  patch.title,
        blurb:  patch.blurb,
        tag:    patch.tag || null,
      });
    }
    cancel();
    await load();
  };

  const remove = async (item) => {
    const ok = window.confirm(`Delete "${item.title}"? This can't be undone.`);
    if (!ok) return;
    try {
      await apiClient.delete(`/admin/roadmap/items/${item.id}`);
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || "Delete failed.");
    }
  };

  const move = async (item, direction) => {
    const col = columns.find((c) => c.key === item.column);
    if (!col) return;
    const ids = col.items.map((i) => i.id);
    const idx = ids.indexOf(item.id);
    const tgt = idx + direction;
    if (tgt < 0 || tgt >= ids.length) return;
    [ids[idx], ids[tgt]] = [ids[tgt], ids[idx]];
    try {
      await apiClient.post("/admin/roadmap/reorder", { column: item.column, ids });
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || "Reorder failed.");
    }
  };

  const columnMap = useMemo(() => {
    const m = {};
    for (const c of columns) m[c.key] = c;
    return m;
  }, [columns]);

  return (
    <main className="roadmap-main" data-testid="roadmap-page">
      <div className="roadmap-hero">
        <Link to="/" className="roadmap-back" data-testid="roadmap-back-link">
          <ArrowLeft size={14} aria-hidden /> Back to app
        </Link>
        <p className="roadmap-eyebrow" data-testid="roadmap-eyebrow">
          FACELESS TO FINISHED · ROADMAP
        </p>
        <h1 className="roadmap-title" data-testid="roadmap-title">
          What we&rsquo;ve shipped. What&rsquo;s next. What we&rsquo;re hearing.
        </h1>
        <p className="roadmap-positioning" data-testid="roadmap-positioning">
          The AI studio for off-camera authority content — built for consultants,
          coaches, experts, and speakers who need a video presence without being
          on camera every day.
        </p>
        <p className="roadmap-sub">
          We update this page in the same change as the code itself — no
          stale promises, no vapor. Want to nudge a &ldquo;Considering&rdquo;
          item into &ldquo;Planned&rdquo;? Email{" "}
          <a className="roadmap-mail" href="mailto:support@c3global.co">
            support@c3global.co
          </a>{" "}
          and tell us why.
        </p>
        {isAdmin && (
          <div className="roadmap-admin-banner" data-testid="roadmap-admin-banner">
            Admin mode — every card is editable. Buyers see the read-only version.
          </div>
        )}
      </div>

      {loading && <div className="roadmap-loading">Loading roadmap…</div>}
      {error && <div className="roadmap-error" data-testid="roadmap-load-error">{error}</div>}

      {!loading && !error && (
        <div className="roadmap-grid">
          {["shipped", "inProgress", "planned", "considering"].map((key) => (
            columnMap[key] ? (
              <RoadmapColumn
                key={key}
                columnKey={key}
                column={columnMap[key]}
                isAdmin={isAdmin}
                editingId={editingId}
                addingInColumn={addingInColumn}
                onStartEdit={startEdit}
                onStartAdd={startAdd}
                onCancel={cancel}
                onSave={save}
                onDelete={remove}
                onMove={move}
              />
            ) : null
          ))}
        </div>
      )}

      <div className="roadmap-footnote">
        <p>
          Building a video engine is a marathon, not a sprint. AppSumo
          buyers locked in the lifetime price for everything on this page —
          shipped, in progress, planned. We&rsquo;re building it because
          you bought it.
        </p>
      </div>
    </main>
  );
}
