import React from 'react';

const PLATFORM_LABELS = {
  youtube: 'YouTube Shorts',
  reels: 'Instagram Reels',
  tiktok: 'TikTok',
};

// Render a Short-Form Script body inside a 9:16 phone-mockup frame.
// Inline [ON-SCREEN: ...] and [B-ROLL: ...] cues are rendered as styled chips
// instead of plain text — this is the "looks like a real video" moment.
export default function PhoneFrame({ scriptBody, platform = 'youtube' }) {
  return (
    <div className="phone-frame" data-platform={platform}>
      <div className="phone-frame-bezel">
        <div className="phone-frame-notch" />
        <div className="phone-frame-status">
          <span className="phone-time">9:41</span>
          <span className="phone-status-right">
            <span className="phone-signal">●●●</span>
            <span className="phone-platform">{PLATFORM_LABELS[platform] || platform}</span>
          </span>
        </div>
        <div className="phone-frame-screen">
          <ScriptWithCues body={scriptBody || ''} />
        </div>
        <div className="phone-frame-home" />
      </div>
    </div>
  );
}

const CUE_RE = /\[(ON-SCREEN|B-ROLL):\s*([^\]]+)\]/g;

function ScriptWithCues({ body }) {
  if (!body) return <div className="phone-empty">Waiting for script…</div>;

  const lines = body.split('\n');

  return (
    <div className="phone-script">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={i} className="phone-spacer" />;

        // Beat headers like [HOOK — 0:00–0:03]
        const beatMatch = trimmed.match(/^\[(HOOK|BODY|CTA)([^\]]*)\]$/i);
        if (beatMatch) {
          return (
            <div key={i} className="phone-beat">
              <span className="phone-beat-label">{beatMatch[1].toUpperCase()}</span>
              <span className="phone-beat-time">{beatMatch[2].replace(/^[\s—–-]+/, '')}</span>
            </div>
          );
        }

        // Standalone cue line ([ON-SCREEN: ...] or [B-ROLL: ...] alone)
        const aloneCue = trimmed.match(/^\[(ON-SCREEN|B-ROLL):\s*([^\]]+)\]$/);
        if (aloneCue) {
          return <Cue key={i} type={aloneCue[1]} text={aloneCue[2]} />;
        }

        // Narration line — split on inline cues and render mixed text + chips
        return <NarrationLine key={i} text={line} />;
      })}
    </div>
  );
}

function NarrationLine({ text }) {
  const parts = [];
  let lastIdx = 0;
  let m;
  CUE_RE.lastIndex = 0;
  while ((m = CUE_RE.exec(text)) !== null) {
    if (m.index > lastIdx) parts.push({ kind: 'text', value: text.slice(lastIdx, m.index) });
    parts.push({ kind: 'cue', type: m[1], value: m[2] });
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < text.length) parts.push({ kind: 'text', value: text.slice(lastIdx) });

  return (
    <p className="phone-narration">
      {parts.map((p, i) =>
        p.kind === 'text'
          ? <span key={i}>{p.value}</span>
          : <Cue key={i} inline type={p.type} text={p.value} />
      )}
    </p>
  );
}

function Cue({ type, text, inline }) {
  const isOnScreen = type.toUpperCase() === 'ON-SCREEN';
  const cls = `cue-chip ${isOnScreen ? 'cue-onscreen' : 'cue-broll'} ${inline ? 'cue-inline' : 'cue-block'}`;
  return (
    <span className={cls}>
      <span className="cue-label">{isOnScreen ? 'TEXT' : 'B-ROLL'}</span>
      <span className="cue-body">{text.trim()}</span>
    </span>
  );
}
