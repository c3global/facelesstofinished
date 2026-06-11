import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { fetchSession } from '../api.js';
import ThemeToggle from '../ThemeToggle.jsx';
import Footer from '../Footer.jsx';

const ACTIVE_STATUSES = new Set(['queued', 'voiceover', 'visuals', 'composing', 'polling']);

function formatCents(cents) {
  const dollars = (Number(cents) || 0) / 100;
  return `$${dollars.toFixed(2)}`;
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return '';
  }
}

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
  const navigate = useNavigate();
  const location = useLocation();

  const [script, setScript] = useState('');
  const [prompts, setPrompts] = useState('');
  const [outputType, setOutputType] = useState('faceless');
  const [aspect, setAspect] = useState('9:16');
  const [captions, setCaptions] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null); // { status, progress, progressLabel, resultUrl, error }
  const [history, setHistory] = useState([]);
  const pollRef = useRef(null);

  const promptLines = useMemo(
    () => prompts.split('\n').map((l) => l.trim()).filter(Boolean),
    [prompts]
  );

  const estimatedCents = useMemo(() => {
    const words = script.split(/\s+/).filter(Boolean).length;
    const seconds = (words / 150) * 60;
    if (outputType === 'avatar') return Math.round(30 + (seconds / 30) * 10);
    return Math.round(10 + promptLines.length * 5);
  }, [outputType, script, promptLines.length]);

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch('/api/studio-history', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setHistory(Array.isArray(data.jobs) ? data.jobs : []);
    } catch {
      // ignore
    }
  }, []);

  // Poll a job until terminal.
  const startPolling = useCallback((jobId) => {
    clearInterval(pollRef.current);
    const tick = async () => {
      try {
        const res = await fetch(`/api/studio-status?jobId=${encodeURIComponent(jobId)}`, {
          credentials: 'include',
        });
        if (!res.ok) return;
        const data = await res.json();
        setJobState(data);
        if (data.status === 'complete' || data.status === 'failed') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          loadHistory();
        }
      } catch {
        // ignore one tick
      }
    };
    tick();
    pollRef.current = setInterval(tick, 5000);
  }, [loadHistory]);

  // Initial load: history + resume from ?job=
  useEffect(() => {
    loadHistory();
    const params = new URLSearchParams(location.search);
    const resumeId = params.get('job');
    if (resumeId) {
      setActiveJobId(resumeId);
      startPolling(resumeId);
    }
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGenerate = async () => {
    setError('');
    if (script.trim().length < 10) {
      setError('Paste a script of at least a few sentences before rendering.');
      return;
    }
    if (promptLines.length === 0) {
      setError('Add at least one B-roll prompt (one per line).');
      return;
    }
    if (promptLines.length > 12) {
      setError('Maximum 12 B-roll prompts. Trim your list.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch('/api/studio-render', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: outputType,
          aspect: aspect === '9:16' ? '9_16' : '16_9',
          captions,
          script: script.trim(),
          prompts: promptLines,
        }),
      });
      if (res.status === 409) {
        setError('You have a render in progress. Wait for it to finish or cancel it from the history below.');
        loadHistory();
        return;
      }
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setError(`Couldn't start render: ${detail.error || res.statusText}`);
        return;
      }
      const data = await res.json();
      setActiveJobId(data.jobId);
      setJobState({
        status: 'queued',
        progress: 0,
        progressLabel: 'Queued',
        resultUrl: null,
        error: null,
      });
      // Reflect in URL so a reload resumes.
      navigate(`/studio?job=${encodeURIComponent(data.jobId)}`, { replace: true });
      startPolling(data.jobId);
      loadHistory();
    } catch (err) {
      setError(`Network error: ${err.message || err}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (!activeJobId) return;
    try {
      await fetch(`/api/studio-cancel?jobId=${encodeURIComponent(activeJobId)}`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch {
      // ignore
    }
    clearInterval(pollRef.current);
    pollRef.current = null;
    setJobState((j) => j ? { ...j, status: 'failed', error: 'canceled by user', progressLabel: 'Canceled' } : j);
    loadHistory();
  };

  const handleStartOver = () => {
    clearInterval(pollRef.current);
    pollRef.current = null;
    setActiveJobId(null);
    setJobState(null);
    navigate('/studio', { replace: true });
  };

  const handleResume = (jobId) => {
    setActiveJobId(jobId);
    setJobState(null);
    navigate(`/studio?job=${encodeURIComponent(jobId)}`, { replace: true });
    startPolling(jobId);
  };

  const isRendering = jobState && ACTIVE_STATUSES.has(jobState.status);

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
            disabled={!!isRendering}
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
            disabled={!!isRendering}
          />
          <p className="studio-helper">Each line becomes one scene. Up to 12 scenes.</p>
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
                  disabled={!!isRendering}
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
                  disabled={!!isRendering}
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
                disabled={!!isRendering}
              />
              <span className="switch" aria-hidden="true">
                <span className="knob" />
              </span>
              <span className="toggle-label">Burn in captions</span>
            </label>
          </div>
        </div>

        <div className="studio-section">
          <p className="studio-cost">Est. ~{formatCents(estimatedCents)}</p>
          <button
            className="generate-btn"
            onClick={handleGenerate}
            disabled={submitting || !!isRendering}
          >
            {submitting ? 'Starting…' : isRendering ? 'Rendering…' : 'Generate video'}
          </button>
          <p className="studio-helper">Estimated render time: ~2-5 min.</p>
          {error && <div className="error">{error}</div>}
        </div>

        {jobState && (
          <div className="studio-render-card">
            {isRendering && (
              <>
                <p>
                  <strong>{jobState.progressLabel || 'Rendering…'}</strong>
                </p>
                <div className="studio-progress">
                  <div className="studio-progress-bar" style={{ width: `${jobState.progress || 0}%` }} />
                </div>
                <p className="studio-render-final">Status: {jobState.status} · {jobState.progress || 0}%</p>
                <button
                  className="header-nav-link"
                  onClick={handleCancel}
                  style={{ marginTop: 10 }}
                >
                  Cancel current render
                </button>
              </>
            )}
            {jobState.status === 'complete' && jobState.resultUrl && (
              <>
                <p><strong>Render complete.</strong></p>
                <video
                  controls
                  src={jobState.resultUrl}
                  style={{ width: '100%', maxHeight: 480, borderRadius: 10, background: '#000' }}
                />
                <div style={{ display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
                  <a className="generate-btn" href={jobState.resultUrl} target="_blank" rel="noreferrer" download>
                    Download MP4
                  </a>
                  <button className="header-nav-link" onClick={handleStartOver}>
                    Start another render
                  </button>
                </div>
              </>
            )}
            {jobState.status === 'failed' && (
              <>
                <p><strong>Render failed.</strong></p>
                <p className="studio-render-final">{jobState.error || 'Unknown error.'}</p>
                <button className="generate-btn" onClick={handleStartOver} style={{ marginTop: 10 }}>
                  Try again
                </button>
              </>
            )}
          </div>
        )}
      </section>

      <section className="studio-history">
        <h3 className="studio-history-title">Recent renders</h3>
        {history.length === 0 ? (
          <div className="studio-empty">
            No renders yet. Your finished videos will appear here.
          </div>
        ) : (
          <ul className="studio-history-list">
            {history.map((j) => (
              <li key={j.id} className="studio-history-row">
                <div className="studio-history-meta">
                  <span className={`studio-chip studio-chip-${j.mode}`}>{j.mode}</span>
                  <span className={`studio-chip studio-chip-status-${j.status}`}>{j.status}</span>
                  <span className="studio-history-date">{formatDate(j.createdAt)}</span>
                </div>
                <div className="studio-history-actions">
                  {j.status === 'complete' && j.resultUrl && (
                    <a className="header-nav-link" href={j.resultUrl} target="_blank" rel="noreferrer">
                      View / Download
                    </a>
                  )}
                  {ACTIVE_STATUSES.has(j.status) && (
                    <button className="header-nav-link" onClick={() => handleResume(j.id)}>
                      Resume
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
