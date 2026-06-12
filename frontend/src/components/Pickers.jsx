import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, Play, Pause, Image as ImageIcon, Film, Sparkles, Layers, Captions, CaptionsOff } from "lucide-react";
import Modal from "./Modal";
import { apiClient } from "../App";

// =====================================================================
// Avatar picker
// =====================================================================
export function AvatarPicker({ open, onClose, value, onPick }) {
  const [avatars, setAvatars] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("all");
  const [aspectFilter, setAspectFilter] = useState("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!open || avatars.length) return;
    setLoading(true);
    apiClient.get("/studio/avatars")
      .then((r) => setAvatars(r.data.avatars || []))
      .catch(() => setAvatars([]))
      .finally(() => setLoading(false));
  }, [open, avatars.length]);

  const filtered = useMemo(() => {
    let list = avatars;
    if (tab !== "all") list = list.filter((a) => a.gender === tab);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((a) => (a.name || "").toLowerCase().includes(q));
    }
    return list;
  }, [avatars, tab, search]);

  const tabs = [
    { id: "all", label: "All" },
    { id: "female", label: "Female" },
    { id: "male", label: "Male" },
    { id: "other", label: "Other" },
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Choose your avatar"
      testId="avatar-modal"
      filters={(
        <>
          <div className="modal-tabs" data-testid="avatar-tabs">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={`modal-tab ${tab === t.id ? "is-active" : ""}`}
                data-testid={`avatar-tab-${t.id}`}
                onClick={() => setTab(t.id)}
              >{t.label}</button>
            ))}
          </div>
          <select
            className="modal-select"
            data-testid="avatar-aspect-filter"
            value={aspectFilter}
            onChange={(e) => setAspectFilter(e.target.value)}
          >
            <option value="all">Any aspect</option>
            <option value="9_16">9:16 vertical</option>
            <option value="16_9">16:9 horizontal</option>
          </select>
          <input
            className="modal-search"
            data-testid="avatar-search-input"
            placeholder="Search avatars…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </>
      )}
    >
      {loading ? (
        <div className="modal-empty">Loading avatars…</div>
      ) : filtered.length === 0 ? (
        <div className="modal-empty">No avatars match. Try clearing filters.</div>
      ) : (
        <div className="avatar-grid" data-testid="avatar-grid">
          {filtered.map((a) => (
            <button
              key={a.id}
              className={`avatar-card ${value?.id === a.id ? "is-selected" : ""}`}
              data-testid={`avatar-card-${a.id}`}
              onClick={() => { onPick(a); onClose(); }}
            >
              {a.preview_image_url ? (
                <img className="avatar-thumb" src={a.preview_image_url} alt={a.name} loading="lazy" />
              ) : (
                <div className="avatar-thumb-empty"><ImageIcon size={28} /></div>
              )}
              <div className="avatar-meta">
                <div className="avatar-name">{a.name}</div>
                <div className="avatar-sub">{a.gender}</div>
              </div>
              {value?.id === a.id && (
                <div className="avatar-check" data-testid={`avatar-check-${a.id}`}><Check size={14} /></div>
              )}
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

// =====================================================================
// Voice picker (HeyGen voices for avatar mode)
// =====================================================================
export function VoicePicker({ open, onClose, value, onPick, source = "heygen" }) {
  // source: "heygen" -> /studio/voices (paired with avatar)
  //         "tts"    -> /studio/tts-voices (Kokoro for faceless mode)
  const [voices, setVoices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("all");
  const [langFilter, setLangFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [playingId, setPlayingId] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    if (voices.length) return;
    setLoading(true);
    const endpoint = source === "tts" ? "/studio/tts-voices" : "/studio/voices";
    apiClient.get(endpoint)
      .then((r) => setVoices(r.data.voices || []))
      .catch(() => setVoices([]))
      .finally(() => setLoading(false));
  }, [open, source, voices.length]);

  // stop audio when closing
  useEffect(() => {
    if (!open && audioRef.current) {
      audioRef.current.pause();
      setPlayingId(null);
    }
  }, [open]);

  const togglePreview = (v) => {
    if (!v.preview_audio) return;
    if (playingId === v.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    if (audioRef.current) audioRef.current.pause();
    const audio = new Audio(v.preview_audio);
    audioRef.current = audio;
    audio.play().catch(() => {});
    audio.onended = () => setPlayingId(null);
    setPlayingId(v.id);
  };

  const languages = useMemo(() => {
    const set = new Set(voices.map((v) => v.language).filter(Boolean));
    return ["all", ...Array.from(set).sort()];
  }, [voices]);

  const filtered = useMemo(() => {
    let list = voices;
    if (tab !== "all") list = list.filter((v) => v.gender === tab);
    if (langFilter !== "all") list = list.filter((v) => v.language === langFilter);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((v) => (v.name || "").toLowerCase().includes(q));
    }
    return list;
  }, [voices, tab, langFilter, search]);

  const tabs = [
    { id: "all", label: "All" },
    { id: "female", label: "Female" },
    { id: "male", label: "Male" },
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Choose your voice"
      testId="voice-modal"
      filters={(
        <>
          <div className="modal-tabs" data-testid="voice-tabs">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={`modal-tab ${tab === t.id ? "is-active" : ""}`}
                data-testid={`voice-tab-${t.id}`}
                onClick={() => setTab(t.id)}
              >{t.label}</button>
            ))}
          </div>
          <select
            className="modal-select"
            data-testid="voice-lang-filter"
            value={langFilter}
            onChange={(e) => setLangFilter(e.target.value)}
          >
            {languages.map((l) => (
              <option key={l} value={l}>{l === "all" ? "Any language" : l}</option>
            ))}
          </select>
          <input
            className="modal-search"
            data-testid="voice-search-input"
            placeholder="Search voices…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </>
      )}
    >
      {loading ? (
        <div className="modal-empty">Loading voices…</div>
      ) : filtered.length === 0 ? (
        <div className="modal-empty">No voices match. Try clearing filters.</div>
      ) : (
        <div className="voice-list" data-testid="voice-list">
          {filtered.map((v) => (
            <div
              key={v.id}
              className={`voice-row ${value?.id === v.id ? "is-selected" : ""}`}
              data-testid={`voice-row-${v.id}`}
            >
              <button
                className="voice-info"
                style={{ background: "transparent", textAlign: "left", flex: 1 }}
                onClick={() => { onPick(v); onClose(); }}
                data-testid={`voice-pick-${v.id}`}
              >
                <div className="voice-name">{v.name}</div>
                <div className="voice-sub">{[v.gender, v.language].filter(Boolean).join(" · ")}</div>
              </button>
              <div className="voice-side">
                {v.preview_audio && (
                  <button
                    className={`voice-play ${playingId === v.id ? "is-playing" : ""}`}
                    data-testid={`voice-play-${v.id}`}
                    onClick={() => togglePreview(v)}
                    aria-label="Preview voice"
                  >
                    {playingId === v.id ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                )}
                {value?.id === v.id && (
                  <div className="avatar-check" style={{ position: "static" }}><Check size={14} /></div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

// =====================================================================
// B-Roll Source picker (faceless mode only)
// =====================================================================
export function BRollSourcePicker({ open, onClose, value, onPick }) {
  const options = [
    { id: "ai",      name: "Generate with AI",  icon: <Sparkles size={22} />, desc: "Every scene is generated with AI from your prompt. Best for abstract, stylized topics." },
    { id: "pexels",  name: "Stock from Pexels", icon: <Film size={22} />,     desc: "Free, premium stock footage. Strong on lifestyle, business, and nature." },
    { id: "pixabay", name: "Stock from Pixabay", icon: <Film size={22} />,    desc: "Alternate library — broader catalog, more niche topics." },
    { id: "mix",     name: "Mix per scene",     icon: <Layers size={22} />,   desc: "No global default — pick AI / Pexels / Pixabay individually for each scene." },
  ];
  return (
    <Modal open={open} onClose={onClose} title="B-Roll source" testId="broll-modal">
      <div className="source-grid" data-testid="broll-grid">
        {options.map((o) => (
          <button
            key={o.id}
            className={`source-card ${value === o.id ? "is-selected" : ""}`}
            data-testid={`broll-${o.id}`}
            onClick={() => { onPick(o.id); onClose(); }}
          >
            <div className="source-icon">{o.icon}</div>
            <div className="source-name">{o.name}</div>
            <div className="source-desc">{o.desc}</div>
          </button>
        ))}
      </div>
    </Modal>
  );
}

// =====================================================================
// Aspect picker
// =====================================================================
export function AspectPicker({ open, onClose, value, onPick }) {
  const options = [
    { id: "9_16",  name: "Vertical 9:16", desc: "Reels, TikTok, YouTube Shorts" },
    { id: "16_9",  name: "Horizontal 16:9", desc: "YouTube long-form, web" },
  ];
  return (
    <Modal open={open} onClose={onClose} title="Aspect ratio" testId="aspect-modal">
      <div className="aspect-list" data-testid="aspect-list">
        {options.map((o) => (
          <button
            key={o.id}
            className={`aspect-row ${value === o.id ? "is-selected" : ""}`}
            data-testid={`aspect-${o.id}`}
            onClick={() => { onPick(o.id); onClose(); }}
          >
            <div className="aspect-info">
              <div className={`aspect-visual is-${o.id.replace("_", "-")}`} />
              <div>
                <div className="aspect-name">{o.name}</div>
                <div className="aspect-sub">{o.desc}</div>
              </div>
            </div>
            {value === o.id && <Check size={20} color="var(--accent)" />}
          </button>
        ))}
      </div>
    </Modal>
  );
}

// =====================================================================
// Captions picker
// =====================================================================
export function CaptionsPicker({ open, onClose, value, onPick }) {
  const options = [
    { id: true,  name: "Captions ON",  desc: "Recommended for vertical short-form (Reels / TikTok / Shorts).", Icon: Captions },
    { id: false, name: "Captions OFF", desc: "Recommended for horizontal long-form (YouTube). Cleaner look.", Icon: CaptionsOff },
  ];
  return (
    <Modal open={open} onClose={onClose} title="Captions" testId="captions-modal">
      <div className="captions-list" data-testid="captions-list">
        {options.map((o) => (
          <button
            key={String(o.id)}
            className={`aspect-row ${value === o.id ? "is-selected" : ""}`}
            data-testid={`captions-${o.id ? "on" : "off"}`}
            onClick={() => { onPick(o.id); onClose(); }}
          >
            <div className="aspect-info">
              <o.Icon size={28} color="var(--accent)" />
              <div>
                <div className="aspect-name">{o.name}</div>
                <div className="aspect-sub">{o.desc}</div>
              </div>
            </div>
            {value === o.id && <Check size={20} color="var(--accent)" />}
          </button>
        ))}
      </div>
    </Modal>
  );
}

// =====================================================================
// Stock search modal (per-scene)
// =====================================================================
export function StockPicker({ open, onClose, sceneIdx, defaultSource, query: defaultQuery, aspect, onPick }) {
  const [source, setSource] = useState(defaultSource === "pixabay" ? "pixabay" : "pexels");
  const [query, setQuery] = useState(defaultQuery || "");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState(null);

  useEffect(() => {
    if (open) {
      setSource(defaultSource === "pixabay" ? "pixabay" : "pexels");
      setQuery(defaultQuery || "");
      setResults([]);
      setPicked(null);
    }
  }, [open, defaultSource, defaultQuery]);

  const search = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const orientation = aspect === "16_9" ? "landscape" : "portrait";
      const r = await apiClient.get("/studio/stock-search", {
        params: { source, q: query.trim(), orientation },
      });
      setResults(r.data.results || []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && query) search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, source]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Scene ${sceneIdx + 1} — stock footage`}
      testId="stock-modal"
      filters={(
        <>
          <div className="modal-tabs">
            <button
              className={`modal-tab ${source === "pexels" ? "is-active" : ""}`}
              data-testid="stock-source-pexels"
              onClick={() => setSource("pexels")}
            >Pexels</button>
            <button
              className={`modal-tab ${source === "pixabay" ? "is-active" : ""}`}
              data-testid="stock-source-pixabay"
              onClick={() => setSource("pixabay")}
            >Pixabay</button>
          </div>
          <input
            className="modal-search"
            data-testid="stock-query-input"
            placeholder="Search keywords…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") search(); }}
          />
          <button className="modal-select" data-testid="stock-search-btn" onClick={search}>Search</button>
        </>
      )}
    >
      <div className="stock-grid" data-testid="stock-grid">
        {loading ? (
          <div className="stock-loading">Searching…</div>
        ) : results.length === 0 ? (
          <div className="stock-empty">Type a keyword and press Enter to search.</div>
        ) : (
          results.map((r) => (
            <button
              key={r.id}
              className={`stock-card ${picked?.id === r.id ? "is-selected" : ""}`}
              data-testid={`stock-card-${r.id}`}
              onClick={() => { setPicked(r); onPick(r); onClose(); }}
            >
              {r.thumb ? (
                <img className={`stock-thumb ${aspect === "16_9" ? "is-landscape" : ""}`} src={r.thumb} alt="" loading="lazy" />
              ) : (
                <div className={`stock-thumb ${aspect === "16_9" ? "is-landscape" : ""}`} />
              )}
              <div className="stock-meta">
                <span className="stock-source">{r.source === "pexels" ? "Pexels" : "Pixabay"}</span>
                {r.duration != null && <span className="stock-duration">{Math.round(r.duration)}s</span>}
              </div>
            </button>
          ))
        )}
      </div>
    </Modal>
  );
}
