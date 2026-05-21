import React, { useRef, useState } from 'react';
import { generateScript } from '../api.js';
import { parseSections } from '../parser.js';
import Markdown from '../Markdown.jsx';

const CARDS = [
  { key: 'concept', title: 'Video Concept', accent: '#7F77DD' },
  { key: 'script', title: 'Full Script', accent: '#1D9E75', large: true },
  { key: 'broll', title: 'B-Roll Shot List', accent: '#378ADD' },
  { key: 'notes', title: 'Production Notes', accent: '#C9956C' },
];

export default function Faceless() {
  const [topic, setTopic] = useState('');
  const [hooks, setHooks] = useState(true);
  const [broll, setBroll] = useState(true);
  const [notes, setNotes] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [raw, setRaw] = useState('');
  const [shake, setShake] = useState(false);
  const inputRef = useRef(null);

  const sections = parseSections(raw);

  const handleGenerate = async () => {
    setError('');
    if (!topic.trim()) {
      setShake(true);
      setError('Enter a topic to generate your script');
      setTimeout(() => setShake(false), 600);
      inputRef.current?.focus();
      return;
    }
    setLoading(true);
    setRaw('');
    try {
      const text = await generateScript({
        topic: topic.trim(),
        includeHooks: hooks,
        includeBRoll: broll,
        includeNotes: notes,
      });
      setRaw(text);
    } catch (e) {
      console.error(e);
      setError('Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setRaw('');
    setError('');
    setTopic('');
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  const fullText = CARDS.map((c) => sections[c.key])
    .filter(Boolean)
    .map((s) => `### ${s.title.toUpperCase()}\n\n${s.body}`)
    .join('\n\n');

  return (
    <div className="page">
      <header className="site-header">
        <div className="brand">C3 Global</div>
        <div className="title-block">
          <h1 className="title">AI Script Engine</h1>
          <div className="tagline">by Faceless to Finished in 48</div>
        </div>
        <div className="brand brand-spacer" aria-hidden="true">C3 Global</div>
      </header>

      <main className="main">
        <section className="hero">
          <input
            ref={inputRef}
            className={`topic-input ${shake ? 'shake' : ''}`}
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Enter your topic or keyword (e.g. How to start investing with $100)"
            disabled={loading}
          />

          <div className="toggles">
            <Toggle label="Include hook variations" checked={hooks} onChange={setHooks} />
            <Toggle label="Include B-roll shot list" checked={broll} onChange={setBroll} />
            <Toggle label="Include production notes" checked={notes} onChange={setNotes} />
          </div>

          <button
            className={`generate-btn ${loading ? 'pulsing' : ''}`}
            onClick={handleGenerate}
            disabled={loading}
          >
            {loading ? 'Generating...' : 'Generate Script'}
          </button>

          {error && <div className="error">{error}</div>}
        </section>

        {raw && (
          <section className="output">
            {CARDS.map((card) => {
              const section = sections[card.key];
              if (!section) return null;
              return (
                <Card
                  key={card.key}
                  title={card.title}
                  accent={card.accent}
                  body={section.body}
                  large={card.large}
                />
              );
            })}

            <div className="output-actions">
              <CopyButton text={fullText} label="Copy Full Script" primary />
              <button className="ghost-btn" onClick={handleReset}>
                Generate New Script
              </button>
            </div>
          </section>
        )}
      </main>

      <footer className="site-footer">
        © 2026 C3 Global · sprint.c3global.co/faceless
      </footer>
    </div>
  );
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="switch" aria-hidden="true">
        <span className="knob" />
      </span>
      <span className="toggle-label">{label}</span>
    </label>
  );
}

function Card({ title, accent, body, large }) {
  return (
    <article className="card" style={{ borderLeftColor: accent }}>
      <header className="card-header">
        <h2 className="card-title" style={{ color: accent }}>{title}</h2>
        <CopyButton text={body} label="Copy" />
      </header>
      <div className={`card-body ${large ? 'card-body-large' : ''}`}>
        <Markdown text={body} />
      </div>
    </article>
  );
}

function CopyButton({ text, label, primary }) {
  const [copied, setCopied] = useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error(e);
    }
  };
  return (
    <button
      className={`copy-btn ${primary ? 'copy-btn-primary' : ''}`}
      onClick={onClick}
    >
      {copied ? 'Copied ✓' : label}
    </button>
  );
}
