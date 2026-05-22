import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { generateScript, fetchSession, loginWithEmail, logout } from '../api.js';
import { parseSections } from '../parser.js';
import Markdown from '../Markdown.jsx';

const STAGE_BY_KEY = {
  angles: 'Generating topic angles…',
  concept: 'Generating video concept…',
  hooks: 'Writing hook variations…',
  outline: 'Mapping the outline…',
  script: 'Writing the full script…',
  transitions: 'Crafting transitions…',
  broll: 'Compiling B-roll shot list…',
  notes: 'Adding production notes…',
};

const STAGE_ORDER = ['angles', 'concept', 'hooks', 'outline', 'script', 'transitions', 'broll', 'notes'];

function detectStage(text) {
  let last = null;
  const re = /###\s+([^\n]+)/g;
  let m;
  while ((m = re.exec(text)) !== null) last = m[1];
  if (!last) return 'Starting…';
  const upper = last.toUpperCase();
  if (upper.includes('TOPIC ANGLE')) return STAGE_BY_KEY.angles;
  if (upper.includes('VIDEO CONCEPT')) return STAGE_BY_KEY.concept;
  if (upper.includes('HOOK')) return STAGE_BY_KEY.hooks;
  if (upper.includes('OUTLINE')) return STAGE_BY_KEY.outline;
  if (upper.includes('NARRATION') || upper.includes('FULL SCRIPT') || upper.includes('SCRIPT')) return STAGE_BY_KEY.script;
  if (upper.includes('TRANSITION')) return STAGE_BY_KEY.transitions;
  if (upper.includes('B-ROLL') || upper.includes('BROLL')) return STAGE_BY_KEY.broll;
  if (upper.includes('PRODUCTION')) return STAGE_BY_KEY.notes;
  return 'Generating…';
}

const LENGTH_OPTIONS = [
  { value: 'short', label: 'Short', sub: '5–8 min' },
  { value: 'medium', label: 'Medium', sub: '10–15 min' },
  { value: 'long', label: 'Long', sub: '18–25 min' },
];

const CARDS = [
  { key: 'angles', title: 'Topic Angles', accent: '#E0A458' },
  { key: 'concept', title: 'Video Concept', accent: '#7F77DD' },
  { key: 'hooks', title: 'Hook Variations', accent: '#C41A18' },
  { key: 'outline', title: 'Outline', accent: '#5BA0F2' },
  { key: 'script', title: 'Full Script', accent: '#1D9E75', large: true },
  { key: 'transitions', title: 'Transitions', accent: '#9C6DD1' },
  { key: 'broll', title: 'B-Roll Shot List', accent: '#378ADD' },
  { key: 'notes', title: 'Production Notes', accent: '#C9956C' },
];

export default function Faceless() {
  const [session, setSession] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(true);

  useEffect(() => {
    fetchSession()
      .then((s) => setSession(s))
      .finally(() => setSessionLoading(false));
  }, []);

  if (sessionLoading) {
    return (
      <div className="page">
        <div className="loading-shell">Loading…</div>
      </div>
    );
  }

  if (!session) {
    return <LoginGate onLogin={(s) => setSession(s)} />;
  }

  return <Engine session={session} onLogout={() => setSession(null)} />;
}

function LoginGate({ onLogin }) {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e?.preventDefault();
    setError('');
    if (!email.trim()) {
      setError('Enter the email you used at checkout.');
      return;
    }
    setLoading(true);
    try {
      const data = await loginWithEmail(email.trim());
      onLogin({ email: data.email });
    } catch (err) {
      if (err.code === 'not_a_buyer') {
        setError("We can't find that email on the buyer list. Use the email you bought with — or email support@c3global.co if you think this is wrong.");
      } else if (err.code === 'invalid_email') {
        setError('That doesn\'t look like a valid email address.');
      } else {
        setError(err.detail ? `Something went wrong. ${err.detail}` : 'Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <header className="site-header">
        <a className="header-logo" href="/faceless" aria-label="Faceless 48">
          <img src="/faceless48-lockup.png" alt="Faceless 48" />
        </a>
        <div className="title-block">
          <h1 className="title">AI Script Engine</h1>
        </div>
        <div className="header-spacer" aria-hidden="true" />
      </header>

      <main className="main">
        <section className="login-card">
          <h2 className="hero-headline">Access your toolkit</h2>
          <p className="hero-sub">
            Enter the email you used when you purchased Faceless to Finished in 48.
          </p>
          <form className="login-form" onSubmit={submit}>
            <input
              className="topic-input"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={loading}
            />
            <button className="generate-btn" type="submit" disabled={loading}>
              {loading ? 'Checking…' : 'Enter'}
            </button>
          </form>
          {error && <div className="error">{error}</div>}
          <p className="login-help">
            Don't have access yet?{' '}
            <a href="https://sprint.c3global.co/faceless" target="_blank" rel="noopener noreferrer">
              Get instant access for $7 →
            </a>
          </p>
        </section>
      </main>

      <footer className="site-footer">
        <img className="footer-mark" src="/faceless48-mark.png" alt="Faceless 48" />
        <div className="footer-text">
          <div>© 2026 C3 Global</div>
        </div>
      </footer>
    </div>
  );
}

function Engine({ session, onLogout }) {
  const [topic, setTopic] = useState('');
  const [videoLength, setVideoLength] = useState('medium');
  const [hooks, setHooks] = useState(true);
  const [broll, setBroll] = useState(true);
  const [notes, setNotes] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [raw, setRaw] = useState('');
  const [progress, setProgress] = useState('');
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
    setProgress('Starting…');
    try {
      const text = await generateScript({
        topic: topic.trim(),
        length: videoLength,
        includeHooks: hooks,
        includeBRoll: broll,
        includeNotes: notes,
        onChunk: (_chunk, accumulated) => {
          setRaw(accumulated);
          setProgress(detectStage(accumulated));
        },
      });
      setRaw(text);
    } catch (e) {
      console.error(e);
      if (e.code === 'unauthorized') {
        setError('Your session expired. Refresh and sign in again.');
      } else {
        setError(e.detail ? `Something went wrong. ${e.detail}` : 'Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
      setProgress('');
    }
  };

  const handleReset = () => {
    setRaw('');
    setError('');
    setTopic('');
    setProgress('');
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  const handleLogout = async () => {
    await logout();
    onLogout();
  };

  const fullText = CARDS.map((c) => sections[c.key])
    .filter(Boolean)
    .map((s) => `### ${s.title.toUpperCase()}\n\n${s.body}`)
    .join('\n\n');

  return (
    <div className="page">
      <header className="site-header">
        <a className="header-logo" href="/faceless" aria-label="Faceless 48 — The 48-Hour Publishing System">
          <img src="/faceless48-lockup.png" alt="Faceless 48 — The 48-Hour Publishing System" />
        </a>
        <div className="title-block">
          <h1 className="title">AI Script Engine</h1>
        </div>
        <nav className="header-nav">
          <Link to="/resources" className="header-nav-link">Resource Library →</Link>
          <button className="header-nav-link header-nav-button" onClick={handleLogout} title={session.email}>
            Sign out
          </button>
        </nav>
      </header>

      <main className="main">
        <section className="hero">
          <div>
            <p className="eyebrow">Faceless to Finished · in 48 hours</p>
            <h2 className="hero-headline">Type a topic.<br/>Get a complete script.</h2>
            <p className="hero-sub">
              A full faceless YouTube video — angles, hooks, outline, narration, B-roll, and production notes — generated in seconds.
            </p>
          </div>

          <div className="input-wrap">
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
          </div>

          <div className="length-picker" role="radiogroup" aria-label="Video length">
            {LENGTH_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={videoLength === opt.value}
                className={`length-option ${videoLength === opt.value ? 'is-selected' : ''}`}
                onClick={() => setVideoLength(opt.value)}
                disabled={loading}
              >
                <span className="length-label">{opt.label}</span>
                <span className="length-sub">{opt.sub}</span>
              </button>
            ))}
          </div>

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
            {loading ? (progress || 'Generating…') : 'Generate Script'}
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
        <img className="footer-mark" src="/faceless48-mark.png" alt="Faceless 48" />
        <div className="footer-text">
          <div>© 2026 C3 Global</div>
        </div>
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
    <article className="card" style={{ borderLeftColor: accent, '--card-accent': accent }}>
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
