import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { generateScript, repurposeAsShort, fetchSession, loginWithEmail, logout } from '../api.js';
import { parseSections } from '../parser.js';
import Markdown from '../Markdown.jsx';
import ThemeToggle from '../ThemeToggle.jsx';
import ResultGrid, { ShortsWorkflow } from '../components/ResultGrid.jsx';
import Footer from '../Footer.jsx';

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

const STAGE_BY_KEY_SHORTS = {
  hooks: 'Writing hook variations…',
  shortScript: 'Writing the short-form script…',
  onScreen: 'Compiling on-screen text…',
  broll: 'Compiling B-roll shot list…',
  caption: 'Crafting the caption…',
  hashtags: 'Picking hashtags…',
  titleVariants: 'Generating title variants…',
  coverPrompts: 'Writing cover image prompts…',
  notes: 'Adding production notes…',
};

const SPRINT_ANGLES = [
  { id: 'curiosity', label: 'Curiosity', accent: '#7F77DD' },
  { id: 'contrarian', label: 'Contrarian', accent: '#C41A18' },
  { id: 'how-to', label: 'How-To', accent: '#1D9E75' },
  { id: 'story', label: 'Story', accent: '#E0A458' },
  { id: 'list', label: 'List', accent: '#378ADD' },
];

const PLATFORM_META = {
  youtube: { label: 'YouTube Shorts', accent: '#FF0033' },
  reels: { label: 'Reels', accent: '#E1306C' },
  tiktok: { label: 'TikTok', accent: '#25F4EE' },
};

function detectStage(text, mode = 'long') {
  let last = null;
  const re = /###\s+([^\n]+)/g;
  let m;
  while ((m = re.exec(text)) !== null) last = m[1];
  if (!last) return 'Starting…';
  const upper = last.toUpperCase();
  if (mode === 'shorts') {
    if (upper.includes('HOOK')) return STAGE_BY_KEY_SHORTS.hooks;
    if (upper.includes('SHORT-FORM SCRIPT') || upper.includes('SHORT FORM SCRIPT')) return STAGE_BY_KEY_SHORTS.shortScript;
    if (upper.includes('ON-SCREEN') || upper.includes('ON SCREEN')) return STAGE_BY_KEY_SHORTS.onScreen;
    if (upper.includes('B-ROLL') || upper.includes('BROLL')) return STAGE_BY_KEY_SHORTS.broll;
    if (upper.includes('CAPTION')) return STAGE_BY_KEY_SHORTS.caption;
    if (upper.includes('HASHTAG')) return STAGE_BY_KEY_SHORTS.hashtags;
    if (upper.includes('COVER IMAGE') || upper.includes('COVER PROMPT')) return STAGE_BY_KEY_SHORTS.coverPrompts;
    if (upper.includes('TITLE') || upper.includes('THUMBNAIL')) return STAGE_BY_KEY_SHORTS.titleVariants;
    if (upper.includes('PRODUCTION')) return STAGE_BY_KEY_SHORTS.notes;
    return 'Generating…';
  }
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

const PLATFORM_OPTIONS = [
  { value: 'youtube', label: 'YouTube Shorts', sub: '15–60s' },
  { value: 'reels', label: 'Instagram Reels', sub: '15–60s' },
  { value: 'tiktok', label: 'TikTok', sub: '21–60s' },
];

const CARDS_LONG = [
  { key: 'angles', title: 'Topic Angles', accent: '#E0A458' },
  { key: 'concept', title: 'Video Concept', accent: '#7F77DD' },
  { key: 'hooks', title: 'Hook Variations', accent: '#C41A18' },
  { key: 'outline', title: 'Outline', accent: '#5BA0F2' },
  { key: 'script', title: 'Full Script', accent: '#1D9E75', large: true },
  { key: 'transitions', title: 'Transitions', accent: '#9C6DD1' },
  { key: 'broll', title: 'B-Roll Shot List', accent: '#378ADD' },
  { key: 'notes', title: 'Production Notes', accent: '#C9956C' },
];

const CARDS_SHORTS = [
  { key: 'hooks', title: 'Hook Variations', accent: '#C41A18' },
  { key: 'shortScript', title: 'Short-Form Script', accent: '#1D9E75', large: true },
  { key: 'onScreen', title: 'On-Screen Text', accent: '#7F77DD' },
  { key: 'broll', title: 'B-Roll Shot List', accent: '#378ADD' },
  { key: 'caption', title: 'Caption', accent: '#5BA0F2' },
  { key: 'hashtags', title: 'Hashtags', accent: '#9C6DD1' },
  { key: 'titleVariants', title: 'Title / Thumbnail Variants', accent: '#E0A458' },
  { key: 'coverPrompts', title: 'Cover Image Prompts', accent: '#E7B23C' },
  { key: 'notes', title: 'Production Notes', accent: '#C9956C' },
];

const SHORTS_CHECKOUT_URL = import.meta.env.VITE_SHORTS_CHECKOUT_URL || 'https://hub.c3global.co/payment-link/6a151b0d3f4eb69bef72feae';

export default function Faceless() {
  const [session, setSession] = useState(null);
  const [sessionLoading, setSessionLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = (markLoading) => {
      if (markLoading) setSessionLoading(true);
      fetchSession()
        .then((s) => { if (!cancelled) setSession(s); })
        .finally(() => { if (!cancelled) setSessionLoading(false); });
    };
    load(true);
    // Re-fetch entitlements when the tab regains focus so newly-granted
    // access (e.g. admin granting shorts in another tab) appears without
    // the user having to log out and back in.
    const onFocus = () => load(false);
    const onVisible = () => {
      if (document.visibilityState === 'visible') load(false);
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisible);
    };
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
        <a className="header-logo" href="/" aria-label="Faceless 48">
          <img src="/faceless48-lockup.png" alt="Faceless 48" />
        </a>
        <div className="title-block">
          <h1 className="title">AI Script Engine</h1>
        </div>
        <nav className="header-nav">
          <ThemeToggle />
        </nav>
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

      <Footer />
    </div>
  );
}

function Engine({ session, onLogout }) {
  const [mode, setMode] = useState('long');
  const [topic, setTopic] = useState('');
  const [videoLength, setVideoLength] = useState('medium');
  const [platform, setPlatform] = useState('youtube');
  const [hooks, setHooks] = useState(true);
  const [broll, setBroll] = useState(true);
  const [notes, setNotes] = useState(true);
  // Shorts-only controls
  const [shortsVariant, setShortsVariant] = useState('single'); // 'single' | 'sprint'
  const [multiPlatform, setMultiPlatform] = useState(false);
  // Long-form -> Shorts repurposer panel state
  const [repurposeOpen, setRepurposeOpen] = useState(false);
  const [repurposePlatform, setRepurposePlatform] = useState('youtube');
  const [repurposeCount, setRepurposeCount] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [raw, setRaw] = useState('');
  const [progress, setProgress] = useState('');
  // Batched results (Sprint, Multi-platform pack, Repurposer) — array of {id, label, accent, platform, raw, status}
  const [batchItems, setBatchItems] = useState(null);
  const [expandedIdx, setExpandedIdx] = useState(0);
  const [shake, setShake] = useState(false);
  const inputRef = useRef(null);

  const entitlements = session.entitlements || [];
  const hasShorts = entitlements.includes('shorts');
  const sections = parseSections(raw);
  const activeCards = mode === 'shorts' ? CARDS_SHORTS : CARDS_LONG;
  const platformAccent = PLATFORM_META[platform]?.accent || '#FF0033';

  const switchMode = (next) => {
    if (next === mode) return;
    setMode(next);
    setRaw('');
    setError('');
    setProgress('');
    setBatchItems(null);
    setRepurposeOpen(false);
  };

  const runBatch = async (specs, runner) => {
    // Initialize all panels in 'pending' state and expand the first.
    const initial = specs.map((s) => ({ ...s, raw: '', status: 'streaming' }));
    setBatchItems(initial);
    setExpandedIdx(0);
    await Promise.all(
      specs.map((spec, i) =>
        runner(spec, (chunk, accumulated) => {
          setBatchItems((prev) => {
            if (!prev) return prev;
            const next = prev.slice();
            next[i] = { ...next[i], raw: accumulated };
            return next;
          });
        })
          .then((finalText) => {
            setBatchItems((prev) => {
              if (!prev) return prev;
              const next = prev.slice();
              next[i] = { ...next[i], raw: finalText, status: 'done' };
              return next;
            });
          })
          .catch((err) => {
            console.error('batch item failed', err);
            setBatchItems((prev) => {
              if (!prev) return prev;
              const next = prev.slice();
              next[i] = { ...next[i], status: 'error' };
              return next;
            });
          })
      )
    );
  };

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
    setBatchItems(null);
    setProgress('Starting…');
    try {
      // Shorts: Sprint mode (5 angles)
      if (mode === 'shorts' && shortsVariant === 'sprint') {
        const specs = SPRINT_ANGLES.map((a) => ({
          id: a.id,
          label: a.label,
          accent: a.accent,
          platform,
          angle: a.id,
        }));
        await runBatch(specs, (spec, onChunk) =>
          generateScript({ mode: 'shorts', topic: topic.trim(), platform: spec.platform, angle: spec.angle, onChunk })
        );
      }
      // Shorts: Multi-platform pack (3 platforms)
      else if (mode === 'shorts' && multiPlatform) {
        const specs = ['youtube', 'reels', 'tiktok'].map((p) => ({
          id: p,
          label: PLATFORM_META[p].label,
          accent: PLATFORM_META[p].accent,
          platform: p,
        }));
        await runBatch(specs, (spec, onChunk) =>
          generateScript({ mode: 'shorts', topic: topic.trim(), platform: spec.platform, onChunk })
        );
      }
      // Single (long or single short)
      else {
        const text = await generateScript({
          mode,
          topic: topic.trim(),
          length: videoLength,
          platform,
          includeHooks: hooks,
          includeBRoll: broll,
          includeNotes: notes,
          onChunk: (_chunk, accumulated) => {
            setRaw(accumulated);
            setProgress(detectStage(accumulated, mode));
          },
        });
        setRaw(text);
      }
    } catch (e) {
      console.error(e);
      if (e.code === 'unauthorized') {
        setError('Your session expired. Refresh and sign in again.');
      } else if (e.code === 'entitlement_required') {
        setError(`You don't own ${e.entitlement === 'shorts' ? 'Faceless Shorts' : 'this feature'} yet.`);
      } else {
        setError(e.detail ? `Something went wrong. ${e.detail}` : 'Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
      setProgress('');
    }
  };

  const handleRepurpose = async () => {
    if (!raw) return;
    if (!hasShorts) return;
    setRepurposeOpen(false);
    setError('');
    setLoading(true);
    try {
      const angles = SPRINT_ANGLES.slice(0, repurposeCount);
      const specs = angles.map((a) => ({
        id: `rp-${a.id}`,
        label: a.label,
        accent: a.accent,
        platform: repurposePlatform,
        angle: a.id,
      }));
      const sourceScript = raw;
      // Move long-form output out of the way visually by stashing batchItems — but keep raw for context.
      await runBatch(specs, (spec, onChunk) =>
        repurposeAsShort({ sourceScript, platform: spec.platform, angle: spec.angle, onChunk })
      );
    } catch (e) {
      console.error(e);
      setError(e.detail || 'Repurpose failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setRaw('');
    setError('');
    setTopic('');
    setProgress('');
    setBatchItems(null);
    setRepurposeOpen(false);
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

  const fullText = activeCards.map((c) => sections[c.key])
    .filter(Boolean)
    .map((s) => `### ${s.title.toUpperCase()}\n\n${s.body}`)
    .join('\n\n');

  return (
    <div className="page" data-mode={mode} data-platform={mode === 'shorts' ? platform : undefined} style={mode === 'shorts' ? { '--platform-accent': platformAccent } : undefined}>
      <header className="site-header">
        <a className="header-logo" href="/" aria-label="Faceless 48 — The 48-Hour Publishing System">
          <img src="/faceless48-lockup.png" alt="Faceless 48 — The 48-Hour Publishing System" />
        </a>
        <div className="title-block">
          <h1 className="title">AI Script Engine</h1>
        </div>
        <nav className="header-nav">
          <ThemeToggle />
          <Link to="/studio" className="header-nav-link">Studio</Link>
          <Link to="/resources" className="header-nav-link">Resource Library →</Link>
          {session.isAdmin && (
            <Link to="/admin" className="header-nav-link">Admin</Link>
          )}
          <button className="header-nav-link header-nav-button" onClick={handleLogout} title={session.email}>
            Sign out
          </button>
        </nav>
      </header>

      <main className={`main ${mode === 'shorts' && hasShorts ? 'main-wide' : ''}`}>
        <section className="hero">
          <div>
            <p className="eyebrow">Faceless to Finished · in 48 hours</p>
            <h2 className="hero-headline">
              {mode === 'shorts' ? <>Type a topic.<br/>Get a short-form script.</> : <>Type a topic.<br/>Get a complete script.</>}
            </h2>
            <p className="hero-sub">
              {mode === 'shorts'
                ? 'A short-form video script — hook, body, CTA, on-screen text, caption, and hashtags — tuned to your platform.'
                : 'A full faceless YouTube video — angles, hooks, outline, narration, B-roll, and production notes — generated in seconds.'}
            </p>
          </div>

          <ModeTabs mode={mode} hasShorts={hasShorts} onChange={switchMode} />

          {mode === 'shorts' && !hasShorts ? (
            <ShortsUpsell />
          ) : (
            <>
              <div className="input-wrap">
                <input
                  ref={inputRef}
                  className={`topic-input ${shake ? 'shake' : ''}`}
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder={mode === 'shorts'
                    ? 'Enter your short-form topic (e.g. 3 productivity hacks that actually work)'
                    : 'Enter your topic or keyword (e.g. How to start investing with $100)'}
                  disabled={loading}
                />
              </div>

              {mode === 'shorts' ? (
                <>
                  <div className="sprint-toggle" role="radiogroup" aria-label="Generation mode">
                    <button
                      type="button"
                      role="radio"
                      aria-checked={shortsVariant === 'single'}
                      className={`sprint-opt ${shortsVariant === 'single' ? 'is-selected' : ''}`}
                      onClick={() => setShortsVariant('single')}
                      disabled={loading}
                    >
                      Single Short
                    </button>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={shortsVariant === 'sprint'}
                      className={`sprint-opt ${shortsVariant === 'sprint' ? 'is-selected' : ''}`}
                      onClick={() => { setShortsVariant('sprint'); setMultiPlatform(false); }}
                      disabled={loading}
                      title="Generate 5 distinct shorts from one topic"
                    >
                      Content Sprint <span className="sprint-badge">5</span>
                    </button>
                  </div>
                  <div className="length-picker" role="radiogroup" aria-label="Platform">
                    {PLATFORM_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        role="radio"
                        aria-checked={platform === opt.value}
                        className={`length-option ${platform === opt.value ? 'is-selected' : ''}`}
                        onClick={() => setPlatform(opt.value)}
                        disabled={loading}
                      >
                        <span className="length-label">{opt.label}</span>
                        <span className="length-sub">{opt.sub}</span>
                      </button>
                    ))}
                  </div>
                  {shortsVariant === 'single' && (
                    <label className={`multi-platform-toggle ${multiPlatform ? 'is-on' : ''}`}>
                      <input
                        type="checkbox"
                        checked={multiPlatform}
                        onChange={(e) => setMultiPlatform(e.target.checked)}
                        disabled={loading}
                      />
                      <span>Generate for all 3 platforms at once</span>
                    </label>
                  )}
                  {shortsVariant === 'sprint' && (
                    <p className="sprint-note">5 shorts on this topic — each from a different angle (Curiosity / Contrarian / How-To / Story / List).</p>
                  )}
                </>
              ) : (
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
              )}

              {mode === 'long' && (
                <div className="toggles">
                  <Toggle label="Include hook variations" checked={hooks} onChange={setHooks} />
                  <Toggle label="Include B-roll shot list" checked={broll} onChange={setBroll} />
                  <Toggle label="Include production notes" checked={notes} onChange={setNotes} />
                </div>
              )}

              <button
                className={`generate-btn ${loading ? 'pulsing' : ''}`}
                onClick={handleGenerate}
                disabled={loading}
              >
                {loading
                  ? (progress || 'Generating…')
                  : mode === 'shorts'
                    ? shortsVariant === 'sprint'
                      ? 'Generate Content Sprint (5)'
                      : multiPlatform
                        ? 'Generate for All 3 Platforms'
                        : 'Generate Short Script'
                    : 'Generate Script'}
              </button>

              {error && <div className="error">{error}</div>}
            </>
          )}
        </section>

        {raw && mode === 'shorts' && (
          <section className="output">
            <ShortsWorkflow sections={sections} platform={platform} />
            <div className="output-actions">
              <CopyButton text={fullText} label="Copy Full Package" primary />
              <button className="ghost-btn" onClick={handleReset}>
                Generate New Short
              </button>
            </div>
          </section>
        )}

        {raw && mode === 'long' && (
          <section className="output">
            <RepurposeCTA
                hasShorts={hasShorts}
                open={repurposeOpen}
                onToggle={() => setRepurposeOpen((v) => !v)}
                platform={repurposePlatform}
                onPlatform={setRepurposePlatform}
                count={repurposeCount}
                onCount={setRepurposeCount}
                onGo={handleRepurpose}
                loading={loading}
              />

            {activeCards.map((card) => {
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

            <p className="history-tip">
              <strong>Tip:</strong> copy your script before generating a new one — we don't save history during the beta.
            </p>

            <div className="output-actions">
              <CopyButton text={fullText} label="Copy Full Script" primary />
              <button className="ghost-btn" onClick={handleReset}>
                Generate New Script
              </button>
            </div>
          </section>
        )}

        {batchItems && batchItems.length > 0 && (
          <section className="output batched-output">
            <header className="batched-header">
              <h3>
                {batchItems[0].id?.startsWith('rp-')
                  ? 'Shorts Derived from Your Script'
                  : batchItems[0].id === 'youtube' || batchItems[0].id === 'reels' || batchItems[0].id === 'tiktok'
                    ? 'Multi-Platform Pack'
                    : 'Content Sprint'}
              </h3>
              <p className="batched-sub">Tap a phone to expand it.</p>
              {batchItems.every((it) => it.status === 'done') && (
                <div className="batched-actions">
                  <CopyButton
                    text={batchItems
                      .map((it) => `# ${it.label?.toUpperCase() || it.id}\n\n${it.raw || ''}`)
                      .join('\n\n---\n\n')}
                    label={`Copy All ${batchItems.length} Shorts`}
                    primary
                  />
                </div>
              )}
            </header>
            <ResultGrid items={batchItems} expandedIdx={expandedIdx} onExpand={setExpandedIdx} />
          </section>
        )}
      </main>

      <Footer />
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

function ModeTabs({ mode, hasShorts, onChange }) {
  return (
    <div className="mode-tabs" role="tablist" aria-label="Generator mode">
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'long'}
        className={`mode-tab ${mode === 'long' ? 'is-selected' : ''}`}
        onClick={() => onChange('long')}
      >
        Full Video
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={mode === 'shorts'}
        className={`mode-tab ${mode === 'shorts' ? 'is-selected' : ''} ${hasShorts ? '' : 'is-locked'}`}
        onClick={() => onChange('shorts')}
      >
        {hasShorts ? null : <span className="mode-lock" aria-hidden="true">🔒</span>}
        Shorts
      </button>
    </div>
  );
}

function ShortsUpsell() {
  return (
    <div className="shorts-upsell">
      <p className="eyebrow">Upgrade</p>
      <h3 className="shorts-upsell-title">Unlock Faceless Shorts</h3>
      <p className="shorts-upsell-sub">
        Generate short-form scripts for YouTube Shorts, Instagram Reels, and TikTok — right inside the tool you're already using. $67 one-time. No subscription.
      </p>
      <ul className="shorts-upsell-list">
        <li><strong>Content Sprint</strong> — generate 5 distinct shorts on one topic in a single click (a week of content per prompt)</li>
        <li><strong>Multi-Platform Pack</strong> — same topic, generated for YouTube Shorts + Reels + TikTok simultaneously</li>
        <li><strong>Cut Long-Form Into Shorts</strong> — turn any full video script into 3–5 ready-to-shoot shorts derived from your own hooks and beats</li>
        <li><strong>AI Cover Image Prompts</strong> — paste-ready Midjourney/Sora prompts for every title variant</li>
        <li>Inline on-screen text + B-roll cues, consolidated shot lists, platform-tuned captions & hashtags</li>
        <li>9:16 phone-mockup preview so your script <em>looks</em> like the final video</li>
      </ul>
      <a
        className="generate-btn shorts-upsell-cta"
        href={SHORTS_CHECKOUT_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        Unlock Faceless Shorts for $67 →
      </a>
      <p className="shorts-upsell-fine">
        Already purchased? Sign out and back in so your access refreshes.
      </p>
    </div>
  );
}

function RepurposeCTA({ hasShorts, open, onToggle, platform, onPlatform, count, onCount, onGo, loading }) {
  if (!hasShorts) {
    return (
      <div className="repurpose-cta repurpose-cta-locked">
        <div className="repurpose-cta-text">
          <strong>Want shorts from this script?</strong>
          <span> Unlock Faceless Shorts to auto-cut this long-form into 3–5 ready-to-shoot shorts.</span>
        </div>
        <a
          className="repurpose-cta-btn"
          href={SHORTS_CHECKOUT_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          🔒 Unlock for $67 →
        </a>
      </div>
    );
  }
  return (
    <div className={`repurpose-cta ${open ? 'is-open' : ''}`}>
      <div className="repurpose-cta-header" onClick={onToggle} role="button" tabIndex={0}>
        <div className="repurpose-cta-text">
          <strong>✂️ Cut into Shorts</strong>
          <span> Auto-derive ready-to-shoot shorts from this script.</span>
        </div>
        <span className="repurpose-chevron">{open ? '▴' : '▾'}</span>
      </div>
      {open && (
        <div className="repurpose-cta-panel">
          <div className="repurpose-row">
            <label>Platform</label>
            <div className="repurpose-pills">
              {PLATFORM_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`repurpose-pill ${platform === opt.value ? 'is-on' : ''}`}
                  onClick={() => onPlatform(opt.value)}
                  disabled={loading}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div className="repurpose-row">
            <label>How many shorts?</label>
            <div className="repurpose-pills">
              {[3, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`repurpose-pill ${count === n ? 'is-on' : ''}`}
                  onClick={() => onCount(n)}
                  disabled={loading}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
          <button className="repurpose-go" onClick={onGo} disabled={loading}>
            {loading ? 'Generating…' : `Generate ${count} Shorts →`}
          </button>
        </div>
      )}
    </div>
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
