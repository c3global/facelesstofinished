import React from "react";

// Parses [HOOK — 0:00–0:03], [BODY — ...], [CTA — ...] blocks from the
// short-form script body. Claude often wraps these markers in markdown bold
// ('**[HOOK — ...]**'), so we strip leading/trailing emphasis from each line
// BEFORE the bracket regex test.
const stripEmphasis = (s) =>
  s
    .replace(/^\s*\*\*\s*/, "")
    .replace(/\s*\*\*\s*$/, "")
    .replace(/^\s*\*\s*/, "")
    .replace(/\s*\*\s*$/, "");

const cleanLine = (s) =>
  s.replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*(.+?)\*/g, "$1");

export default function ShortPhoneBody({ shortBody }) {
  if (!shortBody) return null;

  const blocks = [];
  const lines = shortBody.split(/\r?\n/);
  let current = null;
  for (const rawLn of lines) {
    const ln = stripEmphasis(rawLn);
    const m = ln.match(/^\s*\[(HOOK|BODY|CTA)([^\]]*)\]\s*$/i);
    if (m) {
      if (current) blocks.push(current);
      current = {
        label: m[1].toUpperCase(),
        time: (m[2] || "").replace(/^\s*[—–-]\s*/, "").trim(),
        lines: [],
      };
    } else if (current) {
      const trimmed = ln.trim();
      if (trimmed) current.lines.push(trimmed);
    }
  }
  if (current) blocks.push(current);

  return (
    <div className="phone-body" data-testid="phone-body">
      {blocks.map((b, i) => (
        <div
          key={i}
          className={`phone-beat phone-beat-${b.label.toLowerCase()}`}
          data-testid={`phone-beat-${b.label.toLowerCase()}`}
        >
          <div className="phone-beat-head">
            <span className="phone-beat-label">{b.label}</span>
            {b.time && <span className="phone-beat-time">{b.time}</span>}
          </div>
          <div className="phone-beat-lines">
            {b.lines.map((ln, j) => {
              const isOn = /^\[\s*ON-?SCREEN\s*:/i.test(ln);
              const isBR = /^\[\s*B-?ROLL\s*:/i.test(ln);
              const text = ln.replace(
                /^\[\s*(ON-?SCREEN|B-?ROLL)\s*:\s*([\s\S]*)\]\s*$/i,
                "$2"
              );
              if (isOn)
                return (
                  <div
                    key={j}
                    className="phone-cue phone-cue-onscreen"
                    data-testid="phone-cue-onscreen"
                  >
                    <span className="phone-cue-tag">TEXT</span> {cleanLine(text)}
                  </div>
                );
              if (isBR)
                return (
                  <div
                    key={j}
                    className="phone-cue phone-cue-broll"
                    data-testid="phone-cue-broll"
                  >
                    <span className="phone-cue-tag">B-ROLL</span> {cleanLine(text)}
                  </div>
                );
              return (
                <p key={j} className="phone-narration">
                  {cleanLine(ln)}
                </p>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
