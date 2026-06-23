import React from "react";

// Parses [HOOK — 0:00–0:03], [BODY — ...], [CTA — ...] blocks from the
// short-form script body. Claude often wraps these markers in markdown
// emphasis (`**[HOOK — ...]**`) or inline-code backticks (`` `[ON-SCREEN: ...]` ``),
// so we strip leading/trailing emphasis AND backticks from each line BEFORE
// the bracket regex test. Without backtick stripping, lines like
// `` `[ON-SCREEN: Doing it ALL WRONG]` `` (a real Claude output for the
// YouTube engine) fell through to plain-narration rendering instead of
// becoming a TEXT chip — that's what was making YouTube look "different"
// vs. Reels/TikTok in the compare-all view.
const stripWrappers = (s) =>
  s
    .replace(/^\s*`+\s*/, "")
    .replace(/\s*`+\s*$/, "")
    .replace(/^\s*\*\*\s*/, "")
    .replace(/\s*\*\*\s*$/, "")
    .replace(/^\s*\*\s*/, "")
    .replace(/\s*\*\s*$/, "");

const cleanLine = (s) =>
  s
    .replace(/`+/g, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1");

export default function ShortPhoneBody({ shortBody }) {
  if (!shortBody) return null;

  const blocks = [];
  const lines = shortBody.split(/\r?\n/);
  let current = null;
  for (const rawLn of lines) {
    const ln = stripWrappers(rawLn);
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
              // Strip inline-code backticks from individual cue lines too —
              // Claude sometimes wraps just the bracket-marker in code spans
              // even when the surrounding line isn't otherwise styled.
              const stripped = stripWrappers(ln);
              const isOn = /^\[\s*ON-?SCREEN\s*:/i.test(stripped);
              const isBR = /^\[\s*B-?ROLL\s*:/i.test(stripped);
              const text = stripped.replace(
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
