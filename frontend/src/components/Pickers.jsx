import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, Play, Pause, Image as ImageIcon, Film, Sparkles, Layers, Captions, CaptionsOff, Star } from "lucide-react";
import Modal from "./Modal";
import { apiClient } from "../App";

// =====================================================================
// Avatar picker
// =====================================================================
export function AvatarPicker({ open, onClose, value, onPick, currentAspect = "9_16" }) {
  const [avatars, setAvatars] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("all");
  // Default the aspect filter to whatever the Studio is currently rendering
  // for. Iter-15 left this hard-coded to "all" which meant landscape-only
  // avatars showed up even when the user had picked 9:16 — causing the
  // "Choose your avatar shows the same list for every aspect" bug.
  const [aspectFilter, setAspectFilter] = useState(currentAspect);
  const [search, setSearch] = useState("");
  // Favorites parity with VoicePicker: pin the user's most-used avatars
  // (out of 1281 HeyGen avatars) to the top + dedicated ★ tab.
  const [favorites, setFavorites] = useState(() => new Set());
  const [favTogglingId, setFavTogglingId] = useState(null);

  // Keep the filter in sync if the Studio's aspect changes while the modal
  // is mounted (closed). Opening the modal then will default to the latest.
  useEffect(() => {
    if (!open) setAspectFilter(currentAspect);
  }, [open, currentAspect]);

  useEffect(() => {
    if (!open || avatars.length) return;
    setLoading(true);
    apiClient.get("/studio/avatars")
      .then((r) => setAvatars(r.data.avatars || []))
      .catch(() => setAvatars([]))
      .finally(() => setLoading(false));
  }, [open, avatars.length]);

  // Load the user's favorite avatars the first time the picker opens.
  // Same pattern as VoicePicker: fetch once, mutate through the modal
  // only, so the in-memory Set stays canonical for the session.
  const favoritesLoadedRef = useRef(false);
  useEffect(() => {
    if (!open || favoritesLoadedRef.current) return;
    favoritesLoadedRef.current = true;
    apiClient.get("/studio/avatars/favorites")
      .then((r) => setFavorites(new Set(r.data.favorites || [])))
      .catch(() => {});
  }, [open]);

  const toggleFavorite = async (avatarId) => {
    if (!avatarId || favTogglingId === avatarId) return;
    const isFav = favorites.has(avatarId);
    setFavTogglingId(avatarId);
    setFavorites((prev) => {
      const next = new Set(prev);
      if (isFav) next.delete(avatarId);
      else next.add(avatarId);
      return next;
    });
    try {
      if (isFav) {
        await apiClient.delete(`/studio/avatars/favorites/${encodeURIComponent(avatarId)}`);
      } else {
        await apiClient.post("/studio/avatars/favorites", { avatar_id: avatarId });
      }
    } catch {
      setFavorites((prev) => {
        const next = new Set(prev);
        if (isFav) next.add(avatarId);
        else next.delete(avatarId);
        return next;
      });
    } finally {
      setFavTogglingId(null);
    }
  };

  const filtered = useMemo(() => {
    let list = avatars;
    // Favorites tab: only avatars in the favorites Set (no aspect/gender
    // filters applied — favorites surface across all aspects so the user
    // doesn't lose their pins when flipping between 9:16 and 16:9).
    if (tab === "favorites") {
      list = list.filter((a) => favorites.has(a.id));
      if (search) {
        const q = search.toLowerCase();
        list = list.filter((a) => (a.name || "").toLowerCase().includes(q));
      }
      return list;
    }
    if (tab !== "all") list = list.filter((a) => a.gender === tab);
    // 9:16 is strict: ONLY truly portrait-framed avatars (no "both"). "Both"
    // is a permissive bucket that leaked sit/wide-pose avatars into 9:16
    // and caused HeyGen's cover-crop to chop the subject's body in half.
    // For 16:9 we keep the permissive behaviour — extra avatars are fine.
    if (aspectFilter === "9_16") {
      list = list.filter((a) => a.aspect === "portrait");
    } else if (aspectFilter === "16_9") {
      list = list.filter((a) => a.aspect !== "portrait");
    }
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((a) => (a.name || "").toLowerCase().includes(q));
    }
    // Pin favorites to the top of every non-favorites tab. Stable sort.
    if (favorites.size > 0) {
      list = [
        ...list.filter((a) => favorites.has(a.id)),
        ...list.filter((a) => !favorites.has(a.id)),
      ];
    }
    return list;
  }, [avatars, tab, aspectFilter, search, favorites]);

  const tabs = [
    { id: "favorites", label: "★", title: `Favorites${favorites.size ? ` (${favorites.size})` : ""}` },
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
                title={t.title || t.label}
              >{t.label}{t.id === "favorites" && favorites.size > 0 ? ` ${favorites.size}` : ""}</button>
            ))}
          </div>
          <select
            className="modal-select"
            data-testid="avatar-aspect-filter"
            value={aspectFilter}
            onChange={(e) => setAspectFilter(e.target.value)}
            disabled={tab === "favorites"}
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
        <div className="modal-empty" data-testid="avatar-empty">
          {tab === "favorites"
            ? "No favorite avatars yet — tap the star on any avatar to pin it here."
            : "No avatars match these filters."}
          {tab !== "favorites" && aspectFilter !== "all" && (
            <span style={{ display: "block", marginTop: 6, fontSize: 12, opacity: 0.7 }}>
              Switch the aspect filter to "Any aspect" to widen the search.
            </span>
          )}
        </div>
      ) : (
        <div className="avatar-grid" data-testid="avatar-grid">
          {filtered.map((a) => {
            const isFav = favorites.has(a.id);
            return (
              <button
                key={a.id}
                className={`avatar-card ${value?.id === a.id ? "is-selected" : ""} ${isFav ? "is-favorite" : ""}`}
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
                <button
                  type="button"
                  className={`avatar-fav ${isFav ? "is-on" : ""}`}
                  data-testid={`avatar-fav-${a.id}`}
                  onClick={(e) => { e.stopPropagation(); toggleFavorite(a.id); }}
                  aria-label={isFav ? "Remove from favorites" : "Add to favorites"}
                  aria-pressed={isFav}
                  title={isFav ? "Remove from favorites" : "Add to favorites"}
                >
                  <Star
                    size={16}
                    fill={isFav ? "#E0A458" : "none"}
                    color={isFav ? "#E0A458" : "currentColor"}
                  />
                </button>
                {value?.id === a.id && (
                  <div className="avatar-check" data-testid={`avatar-check-${a.id}`}><Check size={14} /></div>
                )}
              </button>
            );
          })}
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
  // Favorites are user-pinned voice ids. Persisted server-side under the
  // buyer doc so they survive logout/login. Available for HeyGen voices
  // only (the Kokoro TTS list is only 10 entries — favorites would be
  // visual noise). Stored as a Set for O(1) lookup during pin sorting.
  const [favorites, setFavorites] = useState(() => new Set());
  const [favTogglingId, setFavTogglingId] = useState(null);
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

  // Load the user's favorites the first time the picker opens for the
  // HeyGen voices source. We don't reload every open — favorites mutate
  // through this picker only, so the in-memory Set is the source of truth
  // once the initial fetch completes.
  const favoritesLoadedRef = useRef(false);
  useEffect(() => {
    if (!open || source !== "heygen" || favoritesLoadedRef.current) return;
    favoritesLoadedRef.current = true;
    apiClient.get("/studio/voices/favorites")
      .then((r) => setFavorites(new Set(r.data.favorites || [])))
      .catch(() => {});
  }, [open, source]);

  // Toggle a voice in/out of the user's favorites. Optimistically updates
  // the Set; reverts on API failure. Re-clicking the same row before the
  // first request settles is debounced by the favTogglingId guard.
  const toggleFavorite = async (voiceId) => {
    if (!voiceId || favTogglingId === voiceId) return;
    const isFav = favorites.has(voiceId);
    setFavTogglingId(voiceId);
    setFavorites((prev) => {
      const next = new Set(prev);
      if (isFav) next.delete(voiceId);
      else next.add(voiceId);
      return next;
    });
    try {
      if (isFav) {
        await apiClient.delete(`/studio/voices/favorites/${encodeURIComponent(voiceId)}`);
      } else {
        await apiClient.post("/studio/voices/favorites", { voice_id: voiceId });
      }
    } catch {
      // Revert on failure
      setFavorites((prev) => {
        const next = new Set(prev);
        if (isFav) next.add(voiceId);
        else next.delete(voiceId);
        return next;
      });
    } finally {
      setFavTogglingId(null);
    }
  };

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
    // Favorites tab: only voices in the favorites Set.
    if (tab === "favorites") {
      list = list.filter((v) => favorites.has(v.id));
    } else if (tab === "female" || tab === "male") {
      list = list.filter((v) => v.gender === tab);
    } else if (tab === "other") {
      // Show anything that isn't a clean female/male — HeyGen returns these
      // as 'unknown' on ~3% of voices (kid voices, special characters, etc).
      list = list.filter((v) => v.gender !== "female" && v.gender !== "male");
    }
    if (langFilter !== "all") list = list.filter((v) => v.language === langFilter);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((v) => (v.name || "").toLowerCase().includes(q));
    }
    // Pin favorites to the top in every tab except the Favorites tab
    // itself (which is already a favorites-only list). Stable sort so
    // within each bucket the original API order is preserved.
    if (tab !== "favorites" && favorites.size > 0) {
      list = [
        ...list.filter((v) => favorites.has(v.id)),
        ...list.filter((v) => !favorites.has(v.id)),
      ];
    }
    return list;
  }, [voices, tab, langFilter, search, favorites]);

  // Tabs adapt per-source. Kokoro TTS has no favorites concept (only 10
  // voices total) — strip the ⭐ tab there to keep the UI honest.
  const tabs = source === "heygen"
    ? [
        { id: "favorites", label: "★", title: `Favorites${favorites.size ? ` (${favorites.size})` : ""}` },
        { id: "all", label: "All" },
        { id: "female", label: "Female" },
        { id: "male", label: "Male" },
        { id: "other", label: "Neutral" },
      ]
    : [
        { id: "all", label: "All" },
        { id: "female", label: "Female" },
        { id: "male", label: "Male" },
        { id: "other", label: "Neutral" },
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
                title={t.title || t.label}
              >{t.label}{t.id === "favorites" && favorites.size > 0 ? ` ${favorites.size}` : ""}</button>
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
        <div className="modal-empty">
          {tab === "favorites"
            ? "No favorites yet — tap the star on any voice to pin it here."
            : "No voices match. Try clearing filters."}
        </div>
      ) : (
        <div className="voice-list" data-testid="voice-list">
          {filtered.map((v) => {
            const isFav = favorites.has(v.id);
            return (
              <div
                key={v.id}
                className={`voice-row ${value?.id === v.id ? "is-selected" : ""} ${isFav ? "is-favorite" : ""}`}
                data-testid={`voice-row-${v.id}`}
              >
                {source === "heygen" && (
                  <button
                    type="button"
                    className={`voice-fav ${isFav ? "is-on" : ""}`}
                    data-testid={`voice-fav-${v.id}`}
                    onClick={(e) => { e.stopPropagation(); toggleFavorite(v.id); }}
                    aria-label={isFav ? "Remove from favorites" : "Add to favorites"}
                    aria-pressed={isFav}
                    title={isFav ? "Remove from favorites" : "Add to favorites"}
                  >
                    <Star
                      size={16}
                      fill={isFav ? "#E0A458" : "none"}
                      color={isFav ? "#E0A458" : "currentColor"}
                    />
                  </button>
                )}
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
            );
          })}
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
// AI engine picker (Faceless mode only — picks the model for AI scenes)
// =====================================================================
export function AIEnginePicker({ open, onClose, value, onPick, isAdmin = false }) {
  // Engine catalogue. Cost field is only shown to admins per Charity's
  // instruction — customers see a quality/speed hint instead so the UI
  // doesn't expose vendor pricing.
  const options = [
    {
      id: "flux",
      name: "Flux 1.1 Pro · Image + Motion",
      hint: "Fast · low cost. AI-generated still images animated with cinematic camera moves.",
      adminCost: "~$0.04/scene",
      Icon: Sparkles,
    },
    {
      id: "kling",
      name: "Kling 2.1 Master · Cinematic AI Video",
      hint: "Premium cinematic motion. Best for action, characters, and complex scenes.",
      adminCost: "~$0.50/scene",
      Icon: Film,
    },
    {
      id: "veo3",
      name: "Google Veo 3.1 Fast · AI Video",
      hint: "Google's highest fidelity. Best for realistic people, dialogue, and product shots.",
      adminCost: "~$1.00/scene",
      Icon: Film,
    },
    {
      id: "pika",
      name: "Pika 2.1 · AI Video",
      hint: "Stylized AI video. Great for whimsical, dreamy, fashion-style content.",
      adminCost: "~$0.40/scene",
      Icon: Film,
    },
  ];
  return (
    <Modal open={open} onClose={onClose} title="AI engine for AI scenes" testId="ai-engine-modal">
      <div className="source-grid" data-testid="ai-engine-grid">
        {options.map((o) => (
          <button
            key={o.id}
            className={`source-card ${value === o.id ? "is-selected" : ""}`}
            data-testid={`ai-engine-${o.id}`}
            onClick={() => { onPick(o.id); onClose(); }}
          >
            <div className="source-icon"><o.Icon size={22} /></div>
            <div className="source-name">{o.name}</div>
            <div className="source-desc">{o.hint}</div>
            {isAdmin && (
              <div className="source-desc" style={{ marginTop: 6, fontSize: 11, opacity: 0.6 }}>
                {o.adminCost}
              </div>
            )}
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
