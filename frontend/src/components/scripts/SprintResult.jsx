import React from "react";
import PhoneFrame from "../PhoneFrame";
import ShortPhoneBody from "./ShortPhoneBody";

/**
 * SprintResult — renders 5 variant phone frames in a responsive grid.
 * Each variant gets a small header (number, name, angle line, category pill)
 * and a PhoneFrame containing the parsed HOOK/BODY/CTA beats.
 */
export default function SprintResult({ variants, platform }) {
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
        </div>
      ))}
    </div>
  );
}
