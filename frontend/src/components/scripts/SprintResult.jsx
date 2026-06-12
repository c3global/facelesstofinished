import React from "react";
import { ArrowUpRight } from "lucide-react";
import PhoneFrame from "../PhoneFrame";
import ShortPhoneBody from "./ShortPhoneBody";

/**
 * SprintResult — renders 5 variant phone frames in a responsive grid.
 * Each variant gets a small header (number, name, angle line, category pill),
 * a PhoneFrame containing the parsed HOOK/BODY/CTA beats, and a "Promote to
 * full short" button that re-runs the single-Short pipeline for just that
 * variant's angle.
 */
export default function SprintResult({ variants, platform, onPromote, promotingIndex }) {
  if (!variants?.length) return null;
  return (
    <div className="sprint-grid" data-testid="sprint-grid">
      {variants.map((v) => (
        <div
          key={v.index}
          className="sprint-variant"
          data-testid={`sprint-variant-${v.index}`}
        >
          <div className="sprint-variant-head">
            <span className="sprint-variant-num">Variant {v.index} / 5</span>
            <span className="sprint-variant-name">{v.name}</span>
            {v.angle && <span className="sprint-variant-angle">{v.angle}</span>}
            {v.category && (
              <span className="sprint-variant-cat">{v.category}</span>
            )}
          </div>
          <PhoneFrame platform={platform}>
            <ShortPhoneBody shortBody={v.body} />
          </PhoneFrame>
          {onPromote && (
            <button
              type="button"
              className="sprint-variant-promote"
              data-testid={`sprint-variant-${v.index}-promote`}
              disabled={promotingIndex != null}
              onClick={() => onPromote(v)}
            >
              <ArrowUpRight size={13} />
              {promotingIndex === v.index
                ? "Promoting…"
                : "Promote to full short"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
