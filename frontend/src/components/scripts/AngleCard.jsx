import React from "react";
import { Bookmark, BookmarkCheck, ChevronRight } from "lucide-react";

export const ANGLE_CAT = {
  curiosity:  { label: "Curiosity", color: "var(--cat-curiosity)" },
  contrarian: { label: "Contrarian", color: "var(--cat-contrarian)" },
  "how-to":   { label: "How-To", color: "var(--cat-howto)" },
  story:      { label: "Story", color: "var(--cat-story)" },
  list:       { label: "List", color: "var(--cat-list)" },
};

export function AngleCard({ angle, onPick, onSave, isSaved, testid }) {
  const cat = ANGLE_CAT[angle.category] || ANGLE_CAT.curiosity;
  return (
    <div className="angle-card" data-testid={testid} style={{ "--cat-color": cat.color }}>
      <button
        type="button" className="angle-save-btn"
        data-testid={`${testid}-save`}
        onClick={(e) => { e.stopPropagation(); onSave(angle); }}
        aria-label={isSaved ? "Remove from saved angles" : "Save angle for later"}
        title={isSaved ? "Saved" : "Save for later"}
      >
        {isSaved ? <BookmarkCheck size={16} /> : <Bookmark size={16} />}
      </button>
      <button
        type="button" className="angle-card-body"
        data-testid={`${testid}-pick`}
        onClick={() => onPick(angle)}
      >
        <span className="angle-category">{cat.label}</span>
        <span className="angle-name">{angle.name}</span>
        <span className="angle-framing">{angle.framing}</span>
        <span className="angle-pick-hint"><ChevronRight size={12} /> Use this angle</span>
      </button>
    </div>
  );
}
