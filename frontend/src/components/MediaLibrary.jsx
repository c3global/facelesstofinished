import React, { useEffect, useRef, useState } from "react";
import { Upload, Loader2, Trash2, Film, Image as ImageIcon, AlertCircle, Check } from "lucide-react";
import Modal from "./Modal";
import { apiClient } from "../App";

const ALLOWED_BROLL_MIMES = new Set([
  "video/mp4", "video/quicktime", "video/webm", "video/x-matroska",
  "image/png", "image/jpeg", "image/webp", "image/gif",
]);
const MAX_BROLL_BYTES = 100 * 1024 * 1024;

function humanSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Drag-and-drop B-roll library. Shows the user's uploaded clips and lets
 * them pick one for the current scene. Used by the "Your media" scene
 * source option in Studio.jsx.
 *
 * Props:
 *   open, onClose, sceneIdx, aspect
 *   onPick({ video_url, thumb, source: "uploaded" })
 */
export default function MediaLibrary({ open, onClose, sceneIdx, aspect, onPick }) {
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploadingFiles, setUploadingFiles] = useState([]); // [{name, progress, error}]
  const [error, setError] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);
  const dragCounter = useRef(0);

  const reloadList = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/studio/uploads");
      // Filter to broll only (voiceovers live in a different bucket)
      const list = (r.data.uploads || []).filter((u) => (u.kind || "broll") === "broll");
      setUploads(list);
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not load your media.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) reloadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleFiles = async (fileList) => {
    setError("");
    const files = Array.from(fileList || []);
    if (files.length === 0) return;
    const valid = [];
    for (const f of files) {
      const mime = (f.type || "").toLowerCase();
      if (!ALLOWED_BROLL_MIMES.has(mime)) {
        setError(`"${f.name}" — unsupported type. Use MP4, MOV, WEBM, PNG, JPG, WEBP, or GIF.`);
        continue;
      }
      if (f.size > MAX_BROLL_BYTES) {
        setError(`"${f.name}" — too large. Max 100MB per file.`);
        continue;
      }
      valid.push(f);
    }
    if (valid.length === 0) return;

    // Upload one at a time so we can show progress per file.
    for (const f of valid) {
      setUploadingFiles((curr) => [...curr, { name: f.name, progress: 0, error: null }]);
      try {
        const form = new FormData();
        form.append("file", f);
        await apiClient.post("/studio/uploads/broll", form, {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (evt) => {
            const pct = evt.total ? Math.round((evt.loaded / evt.total) * 100) : 0;
            setUploadingFiles((curr) =>
              curr.map((u) => (u.name === f.name ? { ...u, progress: pct } : u))
            );
          },
        });
      } catch (e) {
        setUploadingFiles((curr) =>
          curr.map((u) =>
            u.name === f.name
              ? { ...u, error: e?.response?.data?.detail || "Upload failed" }
              : u
          )
        );
      }
    }
    // Refresh list
    await reloadList();
    // Clear successful uploads
    setUploadingFiles((curr) => curr.filter((u) => u.error));
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    setIsDragging(true);
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setIsDragging(false);
    }
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);
    if (e.dataTransfer?.files?.length) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const deleteUpload = async (id) => {
    try {
      await apiClient.delete(`/studio/uploads/${encodeURIComponent(id)}`);
      setUploads((u) => u.filter((row) => row.id !== id));
    } catch (e) {
      setError(e?.response?.data?.detail || "Could not delete.");
    }
  };

  // The backend needs an absolute URL to download and locally normalize the
  // customer's B-roll media.
  const absoluteUrl = (relativeOrAbs) => {
    if (!relativeOrAbs) return relativeOrAbs;
    if (relativeOrAbs.startsWith("http")) return relativeOrAbs;
    const base = process.env.REACT_APP_BACKEND_URL || "";
    return base.replace(/\/$/, "") + relativeOrAbs;
  };

  const pickItem = (item) => {
    const url = absoluteUrl(item.url);
    onPick({
      video_url: url,
      thumb: (item.content_type || "").startsWith("image/") ? url : null,
      source: "uploaded",
      kind: (item.content_type || "").startsWith("image/") ? "image" : "video",
      filename: item.filename,
    });
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={sceneIdx >= 0 ? `Scene ${sceneIdx + 1} — your media` : "Your media library"}
      testId="media-library-modal"
    >
      <div
        className={`media-dropzone ${isDragging ? "is-dragging" : ""}`}
        data-testid="media-dropzone"
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <Upload size={20} />
        <div className="media-dropzone-title">
          Drop video or image files here
        </div>
        <div className="media-dropzone-hint">
          MP4, MOV, WEBM, PNG, JPG · up to 100MB each
        </div>
        <button
          type="button"
          className="media-dropzone-btn"
          data-testid="media-dropzone-btn"
          onClick={() => fileInputRef.current?.click()}
        >
          Choose files
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="video/*,image/*"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
          data-testid="media-file-input"
        />
      </div>

      {error && (
        <div className="media-error" data-testid="media-library-error">
          <AlertCircle size={12} /> {error}
        </div>
      )}

      {uploadingFiles.length > 0 && (
        <div className="media-uploading-list">
          {uploadingFiles.map((u) => (
            <div key={u.name} className="media-uploading-row">
              <Loader2 size={12} className="spin" />
              <span className="media-uploading-name">{u.name}</span>
              {u.error ? (
                <span className="media-uploading-err">{u.error}</span>
              ) : (
                <span className="media-uploading-pct">{u.progress}%</span>
              )}
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <div className="modal-empty">Loading your media…</div>
      ) : uploads.length === 0 ? (
        <div className="modal-empty" data-testid="media-empty">
          No uploaded media yet. Drop files above or click &ldquo;Choose files&rdquo; to add some.
        </div>
      ) : (
        <div className="media-grid" data-testid="media-grid">
          {uploads.map((m) => {
            const isImage = (m.content_type || "").startsWith("image/");
            const url = absoluteUrl(m.url);
            return (
              <div key={m.id} className="media-card" data-testid={`media-card-${m.id}`}>
                <button
                  type="button"
                  className="media-card-pick"
                  data-testid={`media-pick-${m.id}`}
                  onClick={() => pickItem(m)}
                  title="Use this file for this scene"
                >
                  <div className={`media-card-thumb ${aspect === "16_9" ? "is-landscape" : ""}`}>
                    {isImage ? (
                      <img src={url} alt={m.filename || ""} />
                    ) : (
                      <video src={url} preload="metadata" muted />
                    )}
                    <span className="media-card-kind">
                      {isImage ? <ImageIcon size={11} /> : <Film size={11} />}
                      {isImage ? "Image" : "Video"}
                    </span>
                    {sceneIdx >= 0 && (
                      <span className="media-card-pick-hint">
                        <Check size={12} /> Use here
                      </span>
                    )}
                  </div>
                  <div className="media-card-meta">
                    <div className="media-card-name">{m.filename || "upload"}</div>
                    <div className="media-card-size">{humanSize(m.size)}</div>
                  </div>
                </button>
                <button
                  type="button"
                  className="media-card-delete"
                  data-testid={`media-delete-${m.id}`}
                  onClick={(e) => { e.stopPropagation(); deleteUpload(m.id); }}
                  aria-label="Delete this file"
                  title="Delete"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
