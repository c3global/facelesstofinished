import React, { useEffect, useRef, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { fetchSession } from '../api.js';
import ThemeToggle from '../ThemeToggle.jsx';
import Footer from '../Footer.jsx';

export default function Studio() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSession().then(setSession).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page"><div className="loading-shell">Loading…</div></div>;
  if (!session) return <Navigate to="/" replace />;

  const entitlements = session.entitlements || [];
  const hasStudio = entitlements.includes('studio');

  return (
    <div className="page">
      <header className="site-header">
        <a className="header-logo" href="/" aria-label="Faceless 48 — The 48-Hour Publishing System">
          <img src="/faceless48-lockup.png" alt="Faceless 48 — The 48-Hour Publishing System" />
        </a>
        <div className="title-block">
          <h1 className="title">F2F48 Studio</h1>
        </div>
        <nav className="header-nav">
          <ThemeToggle />
          <Link to="/" className="header-nav-link">Script Engine</Link>
          <Link to="/resources" className="header-nav-link">Resource Library →</Link>
          {session.isAdmin && (
            <Link to="/admin" className="header-nav-link">Admin</Link>
          )}
        </nav>
      </header>

      <main className="main">
        <section className="hero">
          <div>
            <p className="eyebrow">Faceless to Finished · Video Engine</p>
            <h2 className="hero-headline">
              {hasStudio ? <>Render your script<br/>into a finished video.</> : <>Studio is on the way.</>}
            </h2>
            <p className="hero-sub">
              {hasStudio
                ? 'Paste your script, drop in your B-roll prompts, and ship a faceless video — voiceover, visuals, captions, all baked in.'
                : 'A one-click pipeline from script to finished video — voiceover, B-roll, captions. Launching with Faceless to Finished v2.'}
            </p>
          </div>
        </section>

        {!hasStudio ? <StudioUpsell /> : <StudioForm />}
      </main>

      <Footer />
    </div>
  );
}

function StudioUpsell() {
  return (
    <section className="shorts-upsell">
      <p className="eyebrow">Coming Soon</p>
      <h3 className="shorts-upsell-title">Unlock Studio</h3>
      <p className="shorts-upsell-sub">
        Studio is part of the upcoming F2F48 Video Engine. Coming soon.
      </p>
    </section>
  );
}

function StudioForm() {
  const [script, setScript] = useState('');
  const [prompts, setPrompts] = useState('');
  const [outputType, setOutputType] = useState('faceless');
  const [aspect, setAspect] = useState('9:16');
  const [captions, setCaptions] = useState(false);
  const [error, setError] = useState('');
  const [renderState, setRenderState] = useState('idle'); // idle | rendering | done
  const [progress, setProgress] = useState(0);
  const timerRef = useRef(null);

  useEffect(() => () => clearInterval(timerRef.current), []);

  const handleGenerate = () => {
    setError('');
    if (!script.trim()) {
      setError('Paste your script before rendering.');
      return;
    }
    const promptLines = prompts.split('\n').map((l) => l.trim()).filter(Boolean);
    if (promptLines.length === 0) {
      setError('Add at least one B-roll prompt (one per line).');
      return;
    }
    setRenderState('rendering');
    setProgress(0);
    const start = Date.now();
    const DURATION = 3000;
    clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      const elapsed = Date.now() - start;
      const pct = Math.min(100, Math.round((elapsed / DURATION) * 100));
      setProgress(pct);
      if (elapsed >= DURATION) {
        clearInterval(timerRef.current);
        setRenderState('done');
      }
    }, 80);
  };

  return (
    <>
      <section className="studio-form">
        <div className="studio-section">
          <label className="studio-label" htmlFor="studio-script">Your script</label>
          <textarea
            id="studio-script"
            className="studio-textarea"
            rows={8}
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder="Paste the script you generated with F2F48 Script Engine…"
          />
        </div>

        <div className="studio-section">
          <label className="studio-label" htmlFor="studio-prompts">B-roll prompts (one per line)</label>
          <textarea
            id="studio-prompts"
            className="studio-textarea"
            rows={6}
            value={prompts}
            onChange={(e) => setPrompts(e.target.value)}
            placeholder={'Aerial shot of a quiet mountain lake at sunrise\nClose-up of hands typing on a laptop\n…'}
          />
          <p className="studio-helper">Each line becomes one scene.</p>
        </div>

        <div className="studio-section">
          <label className="studio-label">Output settings</label>

          <div className="studio-setting-row">
            <span className="studio-setting-label">Output type</span>
            <div className="length-picker" role="radiogroup" aria-label="Output type">
              {[
                { value: 'faceless', label: 'Faceless' },
                { value: 'avatar', label: 'Avatar' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={outputType === opt.value}
                  className={`length-option ${outputType === opt.value ? 'is-selected' : ''}`}
                  onClick={() => setOutputType(opt.value)}
                >
                  <span className="length-label">{opt.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="studio-setting-row">
            <span className="studio-setting-label">Aspect ratio</span>
            <div className="length-picker" role="radiogroup" aria-label="Aspect ratio">
              {[
                { value: '9:16', label: 'Vertical (9:16)' },
                { value: '16:9', label: 'Horizontal (16:9)' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={aspect === opt.value}
                  className={`length-option ${aspect === opt.value ? 'is-selected' : ''}`}
                  onClick={() => setAspect(opt.value)}
                >
                  <span className="length-label">{opt.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="studio-setting-row">
            <label className="toggle">
              <input
                type="checkbox"
                checked={captions}
                onChange={(e) => setCaptions(e.target.checked)}
              />
              <span className="switch" aria-hidden="true">
                <span className="knob" />
              </span>
              <span className="toggle-label">Burn in captions</span>
            </label>
          </div>
        </div>

        <div className="studio-section">
          <button
            className="generate-btn"
            onClick={handleGenerate}
            disabled={renderState === 'rendering'}
          >
            {renderState === 'rendering' ? 'Rendering…' : 'Generate video'}
          </button>
          <p className="studio-helper">Estimated render time: ~3-8 min.</p>
          {error && <div className="error">{error}</div>}
        </div>

        {renderState !== 'idle' && (
          <div className="studio-render-card">
            <p>
              Render queued. The video engine APIs are being wired up — your first real render will fire once integration is live.
            </p>
            <div className="studio-progress">
              <div className="studio-progress-bar" style={{ width: `${progress}%` }} />
            </div>
            {renderState === 'done' && (
              <p className="studio-render-final">Engine not yet connected.</p>
            )}
          </div>
        )}
      </section>

      <section className="studio-history">
        <h3 className="studio-history-title">Recent renders</h3>
        <div className="studio-empty">
          No renders yet. Your finished videos will appear here.
        </div>
      </section>
    </>
  );
}
