import React from "react";
import { Trash2 } from "lucide-react";
import { ANGLE_CAT } from "./AngleCard";

export default function SavedAnglesPanel({ savedAngles, onApply, onDelete }) {
  if (!savedAngles?.length) return null;
  return (
    <div className="saved-angles-panel" data-testid="saved-angles-panel">
      <div className="saved-angles-head">Saved angles</div>
      <div className="saved-angles-grid">
        {savedAngles.map((s) => {
          const cat = ANGLE_CAT[s.angle.category] || ANGLE_CAT.curiosity;
          return (
            <div
              key={s.id}
              className="saved-angle-card"
              data-testid={`saved-angle-${s.id}`}
              style={{ "--cat-color": cat.color }}
            >
              <button
                type="button"
                className="saved-angle-body"
                data-testid={`saved-angle-${s.id}-use`}
                onClick={() => onApply(s)}
              >
                <span className="angle-category">{cat.label}</span>
                <span className="angle-name">{s.angle.name}</span>
                <span className="angle-framing">{s.angle.framing}</span>
                <span className="saved-angle-topic">Topic: {s.topic}</span>
              </button>
              <button
                type="button"
                className="icon-btn is-danger"
                data-testid={`saved-angle-${s.id}-delete`}
                onClick={() => onDelete(s.id)}
                aria-label="Delete saved angle"
              >
                <Trash2 size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
