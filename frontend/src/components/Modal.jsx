import React, { useEffect } from "react";
import { X } from "lucide-react";

export default function Modal({ open, onClose, title, filters, children, testId }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="modal-scrim"
      data-testid={`${testId}-scrim`}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="modal-card" data-testid={testId} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2 className="modal-title">{title}</h2>
          <button
            className="modal-close"
            data-testid={`${testId}-close`}
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>
        {filters && <div className="modal-filters">{filters}</div>}
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
