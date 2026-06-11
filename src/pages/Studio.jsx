import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { fetchSession } from '../api.js';
import ThemeToggle from '../ThemeToggle.jsx';
import Footer from '../Footer.jsx';

const ACTIVE_STATUSES = new Set(['queued', 'voiceover', 'visuals', 'composing', 'polling']);

const PAGE_SIZE = 24;

const LANG_NAMES = {
  'en-US': 'English (US)', 'en-GB': 'English (UK)', 'en-AU': 'English (Australia)',
  'es-ES': 'Spanish (Spain)', 'es-MX': 'Spanish (Mexico)',
  'fr-FR': 'French', 'de-DE': 'German', 'it-IT': 'Italian',
  'pt-BR': 'Portuguese (Brazil)', 'pt-PT': 'Portuguese (Portugal)',
  'ja-JP': 'Japanese', 'ko-KR': 'Korean', 'zh-CN': 'Chinese (Mainland)',
  'ar-SA': 'Arabic', 'hi-IN': 'Hindi', 'ru-RU': 'Russian',
};

const COMMON_VOICE_LANGS = [
  'en-US', 'en-GB', 'en-AU', 'es-ES', 'es-MX', 'fr-FR', 'de-DE',
  'it-IT', 'pt-BR', 'ja-JP', 'ko-KR', 'zh-CN', 'hi-IN',
];

function langLabel(code) {
  if (!code) return '';
  return LANG_NAMES[code] || code;
}

function normalizeGender(g) {
  const v = String(g || '').toLowerCase();
  if (v === 'female' || v === 'f') return 'female';
  if (v === 'male' || v === 'm') return 'male';
  if (v) return 'other';
  return '';
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString();
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
                ? 'Pick your visuals, voice, and avatar — then ship a finished video.'
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

// Build scene cards from raw prompt text (one line = one scene).
// Preserves any locked stock picks if the prompt text is unchanged.
function syncScenes(promptText, prevScenes, defaultSource = 'ai') {
  const lines = promptText.split('\n').map((l) => l.trim()).filter(Boolean);
  const byPrompt = new Map();
  for (const s of prevScenes) {
    if (s.prompt) byPrompt.set(s.prompt, s);
  }
  const seed = (defaultSource === 'pexels' || defaultSource === 'pixabay') ? defaultSource : 'ai';
  return lines.slice(0, 12).map((prompt, idx) => {
    const prev = byPrompt.get(prompt);
    if (prev) return { ...prev, prompt };
    return {
      id: `scene-${idx}-${Math.random().toString(36).slice(2, 8)}`,
      prompt,
      source: seed,
      videoUrl: '',
      previewImageUrl: '',
      sourceName: '',
    };
  });
}

function StudioForm() {
  const navigate = useNavigate();
  const location = useLocation();

  const [script, setScript] = useState('');
  const [prompts, setPrompts] = useState('');
  const [outputType, setOutputType] = useState('faceless');
  const [brollSource, setBrollSource] = useState('ai'); // 'ai' | 'pexels' | 'pixabay' | 'mix'
  const [ttsVoiceId, setTtsVoiceId] = useState('af_bella'); // Faceless TTS voice (Kokoro)
  const [aspect, setAspect] = useState('9:16');
  const [captions, setCaptions] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [history, setHistory] = useState([]);
  const pollRef = useRef(null);

  // Scenes (faceless)
  const [scenes, setScenes] = useState([]);
  const [stockResults, setStockResults] = useState({}); // { [sceneId]: { source, results, query, loading, error } }

  // Avatars & voices
  const [avatars, setAvatars] = useState(null); // null = not loaded; [] = loaded empty
  const [voices, setVoices] = useState(null);
  const [avatarError, setAvatarError] = useState('');
  const [voiceError, setVoiceError] = useState('');
  const [selectedAvatarId, setSelectedAvatarId] = useState(null);
  const [selectedVoiceId, setSelectedVoiceId] = useState(null);
  const previewAudioRef = useRef(null);
  const [previewingVoiceId, setPreviewingVoiceId] = useState(null);

  // Keep scenes in sync with prompts textarea
  useEffect(() => {
    setScenes((prev) => syncScenes(prompts, prev, brollSource));
  }, [prompts, brollSource]);

  // Load avatars/voices when avatar mode active
  useEffect(() => {
    if (outputType !== 'avatar') return;
    if (avatars === null) {
      fetch('/api/studio-avatars', { credentials: 'include' })
        .then((r) => r.json())
        .then((d) => {
          const list = Array.isArray(d.avatars) ? d.avatars : [];
          setAvatars(list);
          if (d.error && !list.length) setAvatarError(d.error);
          if (list.length && !selectedAvatarId) setSelectedAvatarId(list[0].id);
        })
        .catch((e) => {
          setAvatars([]);
          setAvatarError(String(e?.message || e));
        });
    }
    if (voices === null) {
      fetch('/api/studio-voices', { credentials: 'include' })
        .then((r) => r.json())
        .then((d) => {
          const list = Array.isArray(d.voices) ? d.voices : [];
          setVoices(list);
          if (d.error && !list.length) setVoiceError(d.error);
          if (list.length && !selectedVoiceId) setSelectedVoiceId(list[0].id);
        })
        .catch((e) => {
          setVoices([]);
          setVoiceError(String(e?.message || e));
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputType]);

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch('/api/studio-history', { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setHistory(Array.isArray(data.jobs) ? data.jobs : []);
    } catch { /* ignore */ }
  }, []);

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
      } catch { /* ignore */ }
    };
    tick();
    pollRef.current = setInterval(tick, 5000);
  }, [loadHistory]);

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

  const orientation = aspect === '9:16' ? 'portrait' : 'landscape';

  const runStockSearch = useCallback(async (sceneId, source, query) => {
    setStockResults((prev) => ({
      ...prev,
      [sceneId]: { ...(prev[sceneId] || {}), source, query, loading: true, error: '', results: [] },
    }));
    try {
      const params = new URLSearchParams({ source, query, orientation, perPage: '10' });
      const res = await fetch(`/api/studio-stock-search?${params}`, { credentials: 'include' });
      const data = await res.json().catch(() => ({}));
      setStockResults((prev) => ({
        ...prev,
        [sceneId]: {
          source,
          query,
          loading: false,
          error: data.error || '',
          results: Array.isArray(data.results) ? data.results : [],
        },
      }));
    } catch (err) {
      setStockResults((prev) => ({
        ...prev,
        [sceneId]: { source, query, loading: false, error: String(err?.message || err), results: [] },
      }));
    }
  }, [orientation]);

  // Auto-search stock when global source is Pexels/Pixabay
  useEffect(() => {
    if (outputType !== 'faceless') return;
    if (brollSource !== 'pexels' && brollSource !== 'pixabay') return;
    if (jobState && ACTIVE_STATUSES.has(jobState.status)) return;
    for (const scene of scenes) {
      if (scene.source !== brollSource) continue;
      if (scene.videoUrl) continue;
      const existing = stockResults[scene.id];
      if (existing && (existing.loading || existing.query === scene.prompt)) continue;
      runStockSearch(scene.id, brollSource, scene.prompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brollSource, scenes, outputType]);

  const changeBrollSource = (next) => {
    if (next === brollSource) return;
    const hasLocked = scenes.some((s) => s.videoUrl);
    if (hasLocked && next !== 'mix') {
      // eslint-disable-next-line no-alert
      const ok = window.confirm('Switching source will clear your selected clips. Continue?');
      if (!ok) return;
    }
    setBrollSource(next);
    setScenes((prev) => prev.map((s) => {
      if (next === 'mix') return s; // keep current per-scene state
      if (next === 'ai') {
        return { ...s, source: 'ai', videoUrl: '', previewImageUrl: '', sourceName: '' };
      }
      // pexels or pixabay
      return { ...s, source: next, videoUrl: '', previewImageUrl: '', sourceName: '' };
    }));
  };

  const setSceneSource = (sceneId, source) => {
    setScenes((prev) => prev.map((s) =>
      s.id === sceneId
        ? (source === 'ai'
            ? { ...s, source: 'ai', videoUrl: '', previewImageUrl: '', sourceName: '' }
            : { ...s, source })
        : s
    ));
  };

  const lockSceneStock = (sceneId, result) => {
    setScenes((prev) => prev.map((s) => s.id === sceneId
      ? { ...s, source: result.sourceId, videoUrl: result.videoUrl, previewImageUrl: result.previewImageUrl, sourceName: result.sourceName }
      : s
    ));
  };

  const playVoicePreview = (voice) => {
    if (!voice?.previewAudioUrl) return;
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current = null;
    }
    if (previewingVoiceId === voice.id) {
      setPreviewingVoiceId(null);
      return;
    }
    const audio = new Audio(voice.previewAudioUrl);
    audio.onended = () => setPreviewingVoiceId(null);
    audio.play().catch(() => setPreviewingVoiceId(null));
    previewAudioRef.current = audio;
    setPreviewingVoiceId(voice.id);
  };

  const handleGenerate = async () => {
    setError('');
    if (script.trim().length < 10) {
      setError('Paste a script of at least a few sentences before rendering.');
      return;
    }
    if (outputType === 'faceless') {
      if (scenes.length === 0) {
        setError('Add at least one B-roll prompt (one per line).');
        return;
      }
      if (scenes.length > 12) {
        setError('Maximum 12 scenes. Trim your list.');
        return;
      }
      const invalidStock = scenes.find((s) => (s.source === 'pexels' || s.source === 'pixabay') && !s.videoUrl);
      if (invalidStock) {
        setError('One of your scenes has a stock source selected but no clip picked. Pick a clip or switch back to AI.');
        return;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        mode: outputType,
        aspect: aspect === '9:16' ? '9_16' : '16_9',
        captions,
        script: script.trim(),
      };
      if (outputType === 'avatar') {
        payload.avatarId = selectedAvatarId || '';
        payload.voiceId = selectedVoiceId || '';
      } else {
        payload.scenes = scenes.map((s) => ({
          source: s.source,
          prompt: s.prompt,
          videoUrl: s.videoUrl || undefined,
          previewImageUrl: s.previewImageUrl || undefined,
        }));
        payload.ttsVoiceId = ttsVoiceId || 'af_bella';
      }
      const res = await fetch('/api/studio-render', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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
      setJobState({ status: 'queued', progress: 0, progressLabel: 'Queued', resultUrl: null, error: null });
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
    } catch { /* ignore */ }
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

  const handleDeleteHistory = async (jobId) => {
    // eslint-disable-next-line no-alert
    const ok = window.confirm('Remove this render from history?');
    if (!ok) return;
    const prev = history;
    setHistory((cur) => cur.filter((j) => j.id !== jobId));
    try {
      const res = await fetch(`/api/studio-job-delete?jobId=${encodeURIComponent(jobId)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setHistory(prev);
        // eslint-disable-next-line no-alert
        window.alert(detail.message || detail.error || 'Could not delete this render.');
      }
    } catch (err) {
      setHistory(prev);
      // eslint-disable-next-line no-alert
      window.alert(`Network error: ${err.message || err}`);
    }
  };

  const handleResume = (jobId) => {
    setActiveJobId(jobId);
    setJobState(null);
    navigate(`/studio?job=${encodeURIComponent(jobId)}`, { replace: true });
    startPolling(jobId);
  };

  const isRendering = jobState && ACTIVE_STATUSES.has(jobState.status);

  const selectedAvatar = useMemo(
    () => (avatars || []).find((a) => a.id === selectedAvatarId) || null,
    [avatars, selectedAvatarId]
  );
  const selectedVoice = useMemo(
    () => (voices || []).find((v) => v.id === selectedVoiceId) || null,
    [voices, selectedVoiceId]
  );

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
          <label className="studio-label">Output type</label>
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

        {outputType === 'avatar' && (
          <AvatarSection
            avatars={avatars}
            voices={voices}
            avatarError={avatarError}
            voiceError={voiceError}
            selectedAvatarId={selectedAvatarId}
            setSelectedAvatarId={setSelectedAvatarId}
            selectedVoiceId={selectedVoiceId}
            setSelectedVoiceId={setSelectedVoiceId}
            playVoicePreview={playVoicePreview}
            previewingVoiceId={previewingVoiceId}
            disabled={!!isRendering}
          />
        )}

        {outputType === 'faceless' && (
          <>
            <div className="studio-section">
              <label className="studio-label">B-roll source</label>
              <div className="length-picker" role="radiogroup" aria-label="B-roll source">
                {[
                  { value: 'ai', label: 'Generate with AI' },
                  { value: 'pexels', label: 'Stock from Pexels' },
                  { value: 'pixabay', label: 'Stock from Pixabay' },
                  { value: 'mix', label: 'Mix per scene' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={brollSource === opt.value}
                    className={`length-option ${brollSource === opt.value ? 'is-selected' : ''}`}
                    onClick={() => changeBrollSource(opt.value)}
                    disabled={!!isRendering}
                  >
                    <span className="length-label">{opt.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="studio-section">
              <label className="studio-label" htmlFor="studio-tts-voice">Voiceover</label>
              <select
                id="studio-tts-voice"
                className="studio-textarea"
                value={ttsVoiceId}
                onChange={(e) => setTtsVoiceId(e.target.value)}
                disabled={!!isRendering}
                style={{ height: 44, padding: '0 14px' }}
              >
                <optgroup label="American — Female">
                  <option value="af_bella">Bella — warm, conversational</option>
                  <option value="af_nicole">Nicole — calm, thoughtful</option>
                  <option value="af_sarah">Sarah — clear, professional</option>
                  <option value="af_sky">Sky — bright, upbeat</option>
                  <option value="af_alloy">Alloy — neutral, narrator</option>
                </optgroup>
                <optgroup label="American — Male">
                  <option value="am_adam">Adam — confident, authoritative</option>
                  <option value="am_michael">Michael — friendly, casual</option>
                  <option value="am_eric">Eric — energetic, youthful</option>
                  <option value="am_liam">Liam — steady, narrator</option>
                </optgroup>
                <optgroup label="British — Female">
                  <option value="bf_emma">Emma — refined, articulate</option>
                  <option value="bf_isabella">Isabella — soft, storyteller</option>
                  <option value="bf_alice">Alice — crisp, journalistic</option>
                </optgroup>
                <optgroup label="British — Male">
                  <option value="bm_daniel">Daniel — composed, documentary</option>
                  <option value="bm_george">George — gravelly, dramatic</option>
                  <option value="bm_lewis">Lewis — bright, presenter</option>
                </optgroup>
              </select>
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

            {scenes.length > 0 && (
              <div className="studio-section">
                <label className="studio-label">Scenes</label>
                <div className="studio-scene-list">
                  {scenes.map((scene, idx) => (
                    <SceneCard
                      key={scene.id}
                      idx={idx}
                      scene={scene}
                      brollSource={brollSource}
                      setSceneSource={setSceneSource}
                      runStockSearch={runStockSearch}
                      lockSceneStock={lockSceneStock}
                      stockState={stockResults[scene.id]}
                      disabled={!!isRendering}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        <div className="studio-section">
          <label className="studio-label">Output settings</label>

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

        {/* Storyboard preview */}
        <div className="studio-section">
          <label className="studio-label">Storyboard</label>
          <Storyboard
            outputType={outputType}
            scenes={scenes}
            avatar={selectedAvatar}
            voice={selectedVoice}
          />
        </div>

        <div className="studio-section">
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
                <p><strong>{jobState.progressLabel || 'Rendering…'}</strong></p>
                <div className="studio-progress">
                  <div className="studio-progress-bar" style={{ width: `${jobState.progress || 0}%` }} />
                </div>
                <p className="studio-render-final">Status: {jobState.status} · {jobState.progress || 0}%</p>
                <button className="header-nav-link" onClick={handleCancel} style={{ marginTop: 10 }}>
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

function FilterChips({ label, value, options, onChange, disabled }) {
  return (
    <div className="studio-filter-row" role="group" aria-label={label}>
      <span className="studio-filter-label">{label}</span>
      <div className="studio-filter-chips">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`studio-filter-chip ${value === opt.value ? 'is-active' : ''}`}
            aria-pressed={value === opt.value}
            onClick={() => onChange(opt.value)}
            disabled={disabled}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AvatarPicker({ avatars, avatarError, selectedAvatarId, setSelectedAvatarId, disabled }) {
  const [search, setSearch] = useState('');
  const [gender, setGender] = useState('all');
  const [visible, setVisible] = useState(PAGE_SIZE);

  const list = avatars || [];

  // Available genders to inform facets — but always show the canonical four.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return list.filter((a) => {
      if (q && !String(a.name || '').toLowerCase().includes(q)) return false;
      if (gender !== 'all') {
        const g = normalizeGender(a.gender);
        if (gender === 'other') {
          if (g === 'male' || g === 'female') return false;
        } else if (g !== gender) {
          return false;
        }
      }
      return true;
    });
  }, [list, search, gender]);

  useEffect(() => { setVisible(PAGE_SIZE); }, [search, gender]);

  const hasFilters = !!search.trim() || gender !== 'all';
  const clearFilters = () => { setSearch(''); setGender('all'); };

  return (
    <div className="studio-section">
      <label className="studio-label">Choose your avatar</label>
      {avatars === null && <div className="studio-empty">Loading avatars…</div>}
      {avatars !== null && avatars.length === 0 && (
        <div className="studio-empty">
          {avatarError ? `Couldn't load avatars — please check your account. (${avatarError})` : 'No avatars available.'}
        </div>
      )}
      {avatars && avatars.length > 0 && (
        <>
          <div className="studio-picker-controls">
            <input
              type="search"
              className="studio-picker-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search avatars by name…"
              disabled={disabled}
              aria-label="Search avatars"
            />
            <FilterChips
              label="Gender"
              value={gender}
              onChange={setGender}
              disabled={disabled}
              options={[
                { value: 'all', label: 'All' },
                { value: 'female', label: 'Female' },
                { value: 'male', label: 'Male' },
                { value: 'other', label: 'Other' },
              ]}
            />
            {hasFilters && (
              <button type="button" className="studio-clear-filters" onClick={clearFilters} disabled={disabled}>
                Clear filters
              </button>
            )}
          </div>
          {filtered.length === 0 ? (
            <div className="studio-empty">No avatars match your filters.</div>
          ) : (
            <>
              <div className="studio-avatar-grid">
                {filtered.slice(0, visible).map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    className={`studio-avatar-card ${selectedAvatarId === a.id ? 'is-selected' : ''}`}
                    onClick={() => setSelectedAvatarId(a.id)}
                    disabled={disabled}
                  >
                    {a.previewImageUrl
                      ? <img src={a.previewImageUrl} alt={a.name} loading="lazy" />
                      : <div className="studio-avatar-placeholder" />}
                    <div className="studio-avatar-meta">
                      <div className="studio-avatar-name">{a.name}</div>
                      {a.gender && <div className="studio-avatar-sub">{a.gender}</div>}
                    </div>
                  </button>
                ))}
              </div>
              <div className="studio-picker-footer">
                <span className="studio-picker-count">
                  Showing {Math.min(visible, filtered.length)} of {filtered.length}
                </span>
                {visible < filtered.length && (
                  <button
                    type="button"
                    className="studio-show-more"
                    onClick={() => setVisible((v) => v + PAGE_SIZE)}
                    disabled={disabled}
                  >
                    Show more
                  </button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function VoicePicker({
  voices, voiceError, selectedVoiceId, setSelectedVoiceId,
  playVoicePreview, previewingVoiceId, disabled,
}) {
  const [search, setSearch] = useState('');
  const [gender, setGender] = useState('all');
  const [language, setLanguage] = useState('all');
  const [visible, setVisible] = useState(PAGE_SIZE);

  const list = voices || [];

  // Pull unique languages from data, then intersect/union with common list.
  const availableLangs = useMemo(() => {
    const set = new Set();
    for (const v of list) {
      if (v.language) set.add(v.language);
    }
    return set;
  }, [list]);

  const langOptions = useMemo(() => {
    const codes = COMMON_VOICE_LANGS.filter((c) => availableLangs.has(c));
    // Add any languages not in the common list that exist in data
    const extras = [...availableLangs].filter((c) => !COMMON_VOICE_LANGS.includes(c)).sort();
    return [{ value: 'all', label: 'All languages' }, ...codes.concat(extras).map((c) => ({ value: c, label: langLabel(c) }))];
  }, [availableLangs]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return list.filter((v) => {
      if (q && !String(v.name || '').toLowerCase().includes(q)) return false;
      if (gender !== 'all') {
        const g = normalizeGender(v.gender);
        if (g !== gender) return false;
      }
      if (language !== 'all' && v.language !== language) return false;
      return true;
    });
  }, [list, search, gender, language]);

  useEffect(() => { setVisible(PAGE_SIZE); }, [search, gender, language]);

  const hasFilters = !!search.trim() || gender !== 'all' || language !== 'all';
  const clearFilters = () => { setSearch(''); setGender('all'); setLanguage('all'); };

  return (
    <div className="studio-section">
      <label className="studio-label">Choose your voice</label>
      {voices === null && <div className="studio-empty">Loading voices…</div>}
      {voices !== null && voices.length === 0 && (
        <div className="studio-empty">
          {voiceError ? `Couldn't load voices — please check your account. (${voiceError})` : 'No voices available.'}
        </div>
      )}
      {voices && voices.length > 0 && (
        <>
          <div className="studio-picker-controls">
            <input
              type="search"
              className="studio-picker-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search voices by name…"
              disabled={disabled}
              aria-label="Search voices"
            />
            <FilterChips
              label="Gender"
              value={gender}
              onChange={setGender}
              disabled={disabled}
              options={[
                { value: 'all', label: 'All' },
                { value: 'female', label: 'Female' },
                { value: 'male', label: 'Male' },
              ]}
            />
            <div className="studio-filter-row">
              <span className="studio-filter-label">Language</span>
              <select
                className="studio-filter-select"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                disabled={disabled}
                aria-label="Filter by language"
              >
                {langOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            {hasFilters && (
              <button type="button" className="studio-clear-filters" onClick={clearFilters} disabled={disabled}>
                Clear filters
              </button>
            )}
          </div>
          {filtered.length === 0 ? (
            <div className="studio-empty">No voices match your filters.</div>
          ) : (
            <>
              <div className="studio-voice-list">
                {filtered.slice(0, visible).map((v) => (
                  <div
                    key={v.id}
                    className={`studio-voice-card ${selectedVoiceId === v.id ? 'is-selected' : ''}`}
                    onClick={() => !disabled && setSelectedVoiceId(v.id)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="studio-voice-meta">
                      <div className="studio-voice-name">{v.name}</div>
                      <div className="studio-voice-sub">
                        {[langLabel(v.language), v.gender].filter(Boolean).join(' · ')}
                      </div>
                    </div>
                    {v.previewAudioUrl && (
                      <button
                        type="button"
                        className="studio-voice-play"
                        onClick={(e) => { e.stopPropagation(); playVoicePreview(v); }}
                        aria-label={previewingVoiceId === v.id ? 'Stop preview' : 'Play preview'}
                      >
                        {previewingVoiceId === v.id ? '■' : '▶'}
                      </button>
                    )}
                  </div>
                ))}
              </div>
              <div className="studio-picker-footer">
                <span className="studio-picker-count">
                  Showing {Math.min(visible, filtered.length)} of {filtered.length}
                </span>
                {visible < filtered.length && (
                  <button
                    type="button"
                    className="studio-show-more"
                    onClick={() => setVisible((v) => v + PAGE_SIZE)}
                    disabled={disabled}
                  >
                    Show more
                  </button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function AvatarSection(props) {
  const {
    avatars, voices, avatarError, voiceError,
    selectedAvatarId, setSelectedAvatarId,
    selectedVoiceId, setSelectedVoiceId,
    playVoicePreview, previewingVoiceId, disabled,
  } = props;
  return (
    <>
      <AvatarPicker
        avatars={avatars}
        avatarError={avatarError}
        selectedAvatarId={selectedAvatarId}
        setSelectedAvatarId={setSelectedAvatarId}
        disabled={disabled}
      />
      <VoicePicker
        voices={voices}
        voiceError={voiceError}
        selectedVoiceId={selectedVoiceId}
        setSelectedVoiceId={setSelectedVoiceId}
        playVoicePreview={playVoicePreview}
        previewingVoiceId={previewingVoiceId}
        disabled={disabled}
      />
    </>
  );
}

function SceneCard({ idx, scene, brollSource = 'mix', setSceneSource, runStockSearch, lockSceneStock, stockState, disabled }) {
  const showTabs = brollSource === 'mix';
  const [stockQuery, setStockQuery] = useState(scene.prompt);
  useEffect(() => { setStockQuery(scene.prompt); }, [scene.prompt]);

  const isStock = scene.source === 'pexels' || scene.source === 'pixabay';
  const activeTab = scene.source === 'pexels' || scene.source === 'pixabay' ? scene.source : 'ai';

  const handleTab = (tab) => {
    if (disabled) return;
    setSceneSource(scene.id, tab);
  };

  const handleSearch = () => {
    if (!stockQuery.trim()) return;
    runStockSearch(scene.id, activeTab === 'ai' ? 'pexels' : activeTab, stockQuery.trim());
  };

  return (
    <div className="studio-scene-card">
      <div className="studio-scene-head">
        <span className="studio-scene-num">Scene {idx + 1}</span>
        <span className="studio-scene-prompt">{scene.prompt}</span>
      </div>
      {showTabs && (
        <div className="studio-source-tabs" role="tablist">
          {[
            { v: 'ai', l: 'AI' },
            { v: 'pexels', l: 'Pexels' },
            { v: 'pixabay', l: 'Pixabay' },
          ].map((t) => (
            <button
              key={t.v}
              type="button"
              role="tab"
              aria-selected={activeTab === t.v}
              className={`studio-source-tab ${activeTab === t.v ? 'is-active' : ''}`}
              onClick={() => handleTab(t.v)}
              disabled={disabled}
            >
              {t.l}
            </button>
          ))}
        </div>
      )}

      {activeTab === 'ai' && (
        <div className="studio-scene-body">
          <p className="studio-helper">An image will be generated from your prompt.</p>
        </div>
      )}

      {(activeTab === 'pexels' || activeTab === 'pixabay') && (
        <div className="studio-scene-body">
          <div className="studio-stock-search">
            <input
              type="text"
              className="studio-textarea"
              style={{ minHeight: 0, padding: '8px 12px' }}
              value={stockQuery}
              onChange={(e) => setStockQuery(e.target.value)}
              placeholder="Search clips…"
              disabled={disabled}
            />
            <button
              type="button"
              className="header-nav-link"
              onClick={handleSearch}
              disabled={disabled || !stockQuery.trim()}
            >
              Search
            </button>
          </div>
          {isStock && scene.videoUrl && (
            <p className="studio-helper">
              ✓ Locked from {scene.sourceName || activeTab}.
            </p>
          )}
          {stockState?.loading && <div className="studio-empty">Searching…</div>}
          {stockState && !stockState.loading && stockState.results.length === 0 && (
            <div className="studio-empty">
              {stockState.error ? `No results (${stockState.error}).` : 'No results yet. Try a search.'}
            </div>
          )}
          {stockState?.results?.length > 0 && (
            <div className="studio-stock-grid">
              {stockState.results.map((r) => {
                const isPicked = scene.videoUrl === r.videoUrl;
                return (
                  <button
                    type="button"
                    key={`${r.sourceId}-${r.id}`}
                    className={`studio-stock-card ${isPicked ? 'is-selected' : ''}`}
                    onClick={() => lockSceneStock(scene.id, r)}
                    disabled={disabled}
                  >
                    {r.previewImageUrl
                      ? <img src={r.previewImageUrl} alt="" loading="lazy" />
                      : <div className="studio-stock-placeholder" />}
                    <div className="studio-stock-meta">
                      <span>{r.sourceName}</span>
                      <span>{r.durationSec}s</span>
                    </div>
                    {isPicked && <div className="studio-stock-pick">✓ Selected</div>}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Storyboard({ outputType, scenes, avatar, voice }) {
  if (outputType === 'avatar') {
    if (!avatar && !voice) {
      return <div className="studio-empty">Pick an avatar and voice to preview.</div>;
    }
    return (
      <div className="studio-storyboard">
        <div className="studio-storyboard-card">
          {avatar?.previewImageUrl
            ? <img src={avatar.previewImageUrl} alt={avatar.name} />
            : <div className="studio-storyboard-placeholder" />}
          <div className="studio-storyboard-meta">
            <div className="studio-storyboard-title">{avatar?.name || 'Avatar'}</div>
            <div className="studio-storyboard-sub">{voice?.name || 'Voice'}</div>
          </div>
        </div>
      </div>
    );
  }
  if (scenes.length === 0) {
    return <div className="studio-empty">Add a prompt to preview your storyboard.</div>;
  }
  return (
    <div className="studio-storyboard">
      {scenes.map((s, idx) => (
        <div key={s.id} className="studio-storyboard-card">
          {s.previewImageUrl
            ? <img src={s.previewImageUrl} alt="" />
            : <div className="studio-storyboard-placeholder"><span>AI</span></div>}
          <div className="studio-storyboard-meta">
            <div className="studio-storyboard-title">Scene {idx + 1}</div>
            <div className="studio-storyboard-sub">{s.prompt}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
