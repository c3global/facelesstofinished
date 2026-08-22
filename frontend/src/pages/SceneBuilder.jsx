import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronRight,
  Clapperboard,
  Clock3,
  FileText,
  FolderOpen,
  Image as ImageIcon,
  Layers3,
  Loader2,
  Plus,
  Save,
  Search,
  Sparkles,
  Upload,
} from "lucide-react";
import { apiClient } from "../App";
import MediaLibrary from "../components/MediaLibrary";

const SOURCE_OPTIONS = [
  { id: "unassigned", label: "Decide later", icon: Layers3 },
  { id: "stock", label: "Stock", icon: Search },
  { id: "upload", label: "Your media", icon: Upload },
  { id: "ai", label: "AI visual", icon: Sparkles },
];

function errorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return error?.message || fallback;
}

function projectDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return value;
  }
}

function ProjectDashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ title: "", script: "", aspect: "9:16", target_scene_count: "" });

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiClient.get("/studio/projects");
      setProjects(response.data?.items || []);
    } catch (requestError) {
      setError(errorMessage(requestError, "Could not load Scene Builder projects."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  const createProject = async (event) => {
    event.preventDefault();
    if (!form.script.trim()) return;
    setCreating(true);
    setError("");
    try {
      const payload = {
        title: form.title.trim() || undefined,
        script: form.script,
        aspect: form.aspect,
      };
      if (form.target_scene_count) payload.target_scene_count = Number(form.target_scene_count);
      const response = await apiClient.post("/studio/projects", payload);
      navigate(`/studio/scene-builder/${response.data.project.id}`);
    } catch (requestError) {
      setError(errorMessage(requestError, "Could not create this project."));
    } finally {
      setCreating(false);
    }
  };

  const wordCount = form.script.trim() ? form.script.trim().split(/\s+/).length : 0;

  return (
    <main className="scene-builder-page" data-testid="scene-builder-dashboard">
      <header className="scene-builder-hero">
        <div>
          <p className="scene-builder-eyebrow">Studio · Scene Builder</p>
          <h1>Build the visual story before you render.</h1>
          <p>Match every voiceover passage to the right visual, then review the full plan before any generation begins.</p>
        </div>
        <Link className="scene-builder-quiet-link" to="/studio">
          <ArrowLeft size={14} /> Quick Render
        </Link>
      </header>

      <div className="scene-builder-dashboard-grid">
        <form className="scene-builder-create" onSubmit={createProject}>
          <div className="scene-builder-panel-heading">
            <span className="scene-builder-panel-icon"><Plus size={17} /></span>
            <div>
              <h2>Create a scene plan</h2>
              <p>This does not render or use provider credits.</p>
            </div>
          </div>
          <label className="scene-builder-field">
            <span>Project name <small>optional</small></span>
            <input
              value={form.title}
              maxLength={160}
              onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              placeholder="My next authority video"
              data-testid="scene-builder-title"
            />
          </label>
          <label className="scene-builder-field">
            <span>Script</span>
            <textarea
              value={form.script}
              onChange={(event) => setForm((current) => ({ ...current, script: event.target.value }))}
              placeholder="Paste the finished narration here…"
              rows={12}
              data-testid="scene-builder-script"
            />
            <small>{wordCount.toLocaleString()} words · scene boundaries favor complete sentences</small>
          </label>
          <div className="scene-builder-create-options">
            <label className="scene-builder-field">
              <span>Format</span>
              <select value={form.aspect} onChange={(event) => setForm((current) => ({ ...current, aspect: event.target.value }))}>
                <option value="9:16">9:16 Vertical</option>
                <option value="16:9">16:9 Landscape</option>
                <option value="1:1">1:1 Square</option>
              </select>
            </label>
            <label className="scene-builder-field">
              <span>Scenes <small>optional</small></span>
              <input
                type="number"
                min="1"
                max="200"
                value={form.target_scene_count}
                onChange={(event) => setForm((current) => ({ ...current, target_scene_count: event.target.value }))}
                placeholder="Auto"
              />
            </label>
          </div>
          {error && <div className="scene-builder-error"><AlertCircle size={15} /> {error}</div>}
          <button className="scene-builder-primary" type="submit" disabled={creating || !form.script.trim()}>
            {creating ? <Loader2 size={16} className="spin" /> : <Clapperboard size={16} />}
            {creating ? "Building scenes…" : "Create scene plan"}
          </button>
        </form>

        <section className="scene-builder-projects" aria-label="Scene Builder projects">
          <div className="scene-builder-panel-heading">
            <span className="scene-builder-panel-icon"><FolderOpen size={17} /></span>
            <div>
              <h2>Your projects</h2>
              <p>Continue a saved scene plan.</p>
            </div>
          </div>
          {loading ? (
            <div className="scene-builder-empty"><Loader2 size={18} className="spin" /> Loading projects…</div>
          ) : projects.length === 0 ? (
            <div className="scene-builder-empty">
              <Clapperboard size={24} />
              <strong>No scene plans yet</strong>
              <span>Your first project will appear here automatically.</span>
            </div>
          ) : (
            <div className="scene-builder-project-list">
              {projects.map((project) => (
                <button
                  type="button"
                  className="scene-builder-project-row"
                  key={project.id}
                  onClick={() => navigate(`/studio/scene-builder/${project.id}`)}
                >
                  <span className="scene-builder-project-thumb"><Clapperboard size={18} /></span>
                  <span className="scene-builder-project-copy">
                    <strong>{project.title}</strong>
                    <small>{project.aspect} · Revision {project.current_revision_number} · {projectDate(project.updated_at)}</small>
                  </span>
                  <ChevronRight size={17} />
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function SaveState({ status }) {
  if (status === "saving") return <span className="scene-builder-save is-saving"><Loader2 size={13} className="spin" /> Saving…</span>;
  if (status === "saved") return <span className="scene-builder-save is-saved"><Check size={13} /> Saved</span>;
  if (status === "conflict") return <span className="scene-builder-save is-conflict"><AlertCircle size={13} /> Reload needed</span>;
  if (status === "error") return <span className="scene-builder-save is-conflict"><AlertCircle size={13} /> Save failed</span>;
  return <span className="scene-builder-save"><Clock3 size={13} /> Unsaved changes</span>;
}

function SceneEditor({ projectId }) {
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [revision, setRevision] = useState(null);
  const [scenes, setScenes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveStatus, setSaveStatus] = useState("saved");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeSceneId, setActiveSceneId] = useState(null);
  const [mediaSceneId, setMediaSceneId] = useState(null);
  const editGeneration = useRef(0);

  const hydrate = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiClient.get(`/studio/projects/${projectId}`);
      setProject(response.data.project);
      setRevision(response.data.revision);
      setScenes(response.data.revision.scenes || []);
      setActiveSceneId(response.data.revision.scenes?.[0]?.id || null);
      setDirty(false);
      setSaveStatus("saved");
      editGeneration.current = 0;
    } catch (requestError) {
      setError(errorMessage(requestError, "Could not load this scene plan."));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { hydrate(); }, [hydrate]);

  const markChanged = useCallback((updater) => {
    editGeneration.current += 1;
    setScenes(updater);
    setDirty(true);
    setSaveStatus("dirty");
  }, []);

  const updateScene = useCallback((sceneId, section, patch) => {
    markChanged((current) => current.map((scene) => (
      scene.id === sceneId ? { ...scene, [section]: { ...scene[section], ...patch } } : scene
    )));
  }, [markChanged]);

  const saveDraft = useCallback(async () => {
    if (!dirty || saving || !revision || saveStatus === "conflict" || saveStatus === "error") return;
    const generation = editGeneration.current;
    setSaving(true);
    setSaveStatus("saving");
    try {
      const response = await apiClient.put(`/studio/projects/${projectId}/revisions`, {
        expected_revision: revision.version,
        script: revision.script,
        scenes,
        voiceover: revision.voiceover,
        change_summary: "Scene Builder autosave",
      });
      setProject(response.data.project);
      setRevision(response.data.revision);
      if (editGeneration.current === generation) {
        setDirty(false);
        setSaveStatus("saved");
      } else {
        setSaveStatus("dirty");
      }
    } catch (requestError) {
      if (requestError?.response?.status === 409) {
        setSaveStatus("conflict");
        setError("This project changed in another tab or session. Reload it before making more edits.");
      } else {
        setSaveStatus("error");
        setError(errorMessage(requestError, "Your changes could not be saved."));
      }
    } finally {
      setSaving(false);
    }
  }, [dirty, projectId, revision, saveStatus, saving, scenes]);

  useEffect(() => {
    if (!dirty || saving || saveStatus === "conflict" || saveStatus === "error") return undefined;
    const timer = window.setTimeout(saveDraft, 1000);
    return () => window.clearTimeout(timer);
  }, [dirty, saveDraft, saveStatus, saving, scenes]);

  const activeScene = useMemo(
    () => scenes.find((scene) => scene.id === activeSceneId) || scenes[0] || null,
    [activeSceneId, scenes],
  );
  const assignedCount = scenes.filter((scene) => scene.visual?.source !== "unassigned").length;
  const progress = scenes.length ? Math.round((assignedCount / scenes.length) * 100) : 0;

  if (loading) {
    return <main className="scene-builder-page"><div className="scene-builder-loading"><Loader2 className="spin" /> Loading your scene plan…</div></main>;
  }
  if (!project || !revision) {
    return (
      <main className="scene-builder-page">
        <div className="scene-builder-fatal"><AlertCircle size={24} /><h1>Scene plan unavailable</h1><p>{error}</p><button onClick={() => navigate("/studio/scene-builder")}>Back to projects</button></div>
      </main>
    );
  }

  return (
    <main className="scene-builder-editor" data-testid="scene-builder-editor">
      <header className="scene-builder-editor-header">
        <div className="scene-builder-editor-heading">
          <button type="button" className="scene-builder-icon-button" onClick={() => navigate("/studio/scene-builder")} aria-label="Back to projects"><ArrowLeft size={17} /></button>
          <div>
            <p>Scene Builder · {project.aspect}</p>
            <h1>{project.title}</h1>
          </div>
        </div>
        <div className="scene-builder-editor-actions">
          <SaveState status={saveStatus} />
          <button type="button" className="scene-builder-secondary" onClick={saveDraft} disabled={!dirty || saving || saveStatus === "conflict"}>
            <Save size={15} /> Save now
          </button>
        </div>
      </header>

      {error && (
        <div className="scene-builder-editor-alert">
          <AlertCircle size={15} /><span>{error}</span>
          {saveStatus === "conflict" && <button type="button" onClick={hydrate}>Reload latest</button>}
          {saveStatus === "error" && <button type="button" onClick={() => { setError(""); setSaveStatus("dirty"); }}>Try again</button>}
        </div>
      )}

      <div className="scene-builder-progressbar" aria-label={`${assignedCount} of ${scenes.length} scenes have visuals assigned`}>
        <div><span style={{ width: `${progress}%` }} /></div>
        <small>{assignedCount} of {scenes.length} scenes visually planned</small>
      </div>

      <div className="scene-builder-workspace">
        <section className="scene-builder-scene-column" aria-label="Narration scenes">
          <div className="scene-builder-column-head">
            <div><h2>Scenes</h2><p>Each card is locked to its exact narration passage.</p></div>
            <span>{scenes.length}</span>
          </div>
          <div className="scene-builder-scene-list">
            {scenes.map((scene, index) => {
              const isActive = activeScene?.id === scene.id;
              const source = SOURCE_OPTIONS.find((option) => option.id === scene.visual?.source) || SOURCE_OPTIONS[0];
              const SourceIcon = source.icon;
              return (
                <button
                  type="button"
                  key={scene.id}
                  className={`scene-builder-scene-row ${isActive ? "is-active" : ""}`}
                  onClick={() => setActiveSceneId(scene.id)}
                  data-testid={`scene-builder-scene-${index}`}
                >
                  <span className="scene-builder-scene-number">{String(index + 1).padStart(2, "0")}</span>
                  <span className="scene-builder-scene-copy">
                    <strong>{scene.narration.text}</strong>
                    <small>Words {scene.narration.word_start + 1}–{scene.narration.word_end}</small>
                  </span>
                  <span className={`scene-builder-source-chip is-${source.id}`}><SourceIcon size={12} /> {source.label}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="scene-builder-inspector" aria-label="Scene visual editor">
          {activeScene && (
            <>
              <div className="scene-builder-preview">
                {activeScene.visual?.asset_url ? (
                  activeScene.visual.asset_kind === "video" ? (
                    <video src={activeScene.visual.asset_url} controls preload="metadata" />
                  ) : (
                    <img src={activeScene.visual.asset_url} alt="Selected B-roll" />
                  )
                ) : (
                  <div className="scene-builder-preview-empty">
                    <ImageIcon size={28} />
                    <strong>Scene {activeScene.order + 1} visual</strong>
                    <span>Choose a source and describe what should appear here.</span>
                  </div>
                )}
                <span className="scene-builder-preview-badge">{project.aspect}</span>
              </div>

              <div className="scene-builder-narration-card">
                <span><FileText size={13} /> Narration</span>
                <p>{activeScene.narration.text}</p>
                <small>
                  {activeScene.narration.start_ms == null
                    ? "Audio timing will be measured after a voiceover is selected."
                    : `${(activeScene.narration.start_ms / 1000).toFixed(1)}s–${(activeScene.narration.end_ms / 1000).toFixed(1)}s`}
                </small>
              </div>

              <fieldset className="scene-builder-source-picker">
                <legend>Visual source</legend>
                <div>
                  {SOURCE_OPTIONS.map((option) => {
                    const Icon = option.icon;
                    return (
                      <button
                        type="button"
                        key={option.id}
                        className={activeScene.visual?.source === option.id ? "is-active" : ""}
                        onClick={() => {
                          updateScene(activeScene.id, "visual", { source: option.id });
                          if (option.id === "upload") setMediaSceneId(activeScene.id);
                        }}
                      ><Icon size={14} /> {option.label}</button>
                    );
                  })}
                </div>
              </fieldset>

              <label className="scene-builder-field">
                <span>Detailed visual direction</span>
                <textarea
                  rows={4}
                  value={activeScene.visual?.detailed_prompt || ""}
                  onChange={(event) => updateScene(activeScene.id, "visual", { detailed_prompt: event.target.value })}
                  placeholder="Describe the exact visual, mood, framing, action, and setting…"
                  data-testid="scene-builder-detailed-prompt"
                />
                <small>Used as creative direction for AI visuals and as your reference when choosing uploaded media.</small>
              </label>

              <label className="scene-builder-field">
                <span>Stock-search keywords</span>
                <input
                  value={activeScene.visual?.stock_query || ""}
                  onChange={(event) => updateScene(activeScene.id, "visual", { stock_query: event.target.value })}
                  placeholder="Example: woman recording laptop tutorial"
                  data-testid="scene-builder-stock-query"
                />
                <small>Short, literal keywords only. Stock search itself will be connected after this editor is approved.</small>
              </label>

              {activeScene.visual?.source === "upload" && (
                <button type="button" className="scene-builder-upload-button" onClick={() => setMediaSceneId(activeScene.id)}>
                  <Upload size={15} /> {activeScene.visual.asset_url ? "Replace uploaded media" : "Choose uploaded B-roll"}
                </button>
              )}
              {activeScene.visual?.source === "stock" && (
                <div className="scene-builder-connection-note"><Search size={14} /> Stock results are intentionally disabled in this preview. Your saved query is ready for the next connection.</div>
              )}
              {activeScene.visual?.source === "ai" && (
                <div className="scene-builder-connection-note"><Sparkles size={14} /> No image will be generated in this preview. The detailed direction is saved without spending credits.</div>
              )}
            </>
          )}
        </section>
      </div>

      <MediaLibrary
        open={!!mediaSceneId}
        onClose={() => setMediaSceneId(null)}
        sceneIdx={scenes.findIndex((scene) => scene.id === mediaSceneId)}
        aspect={project.aspect}
        onPick={(media) => {
          if (!mediaSceneId) return;
          updateScene(mediaSceneId, "visual", {
            source: "upload",
            asset_url: media.video_url,
            asset_kind: media.kind,
            asset_id: media.asset_id || null,
          });
          setMediaSceneId(null);
        }}
      />
    </main>
  );
}

export default function SceneBuilder() {
  const { projectId } = useParams();
  return projectId ? <SceneEditor projectId={projectId} /> : <ProjectDashboard />;
}
