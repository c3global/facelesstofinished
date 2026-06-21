import React, { useEffect, useRef, useState } from "react";
import { Mic, Square, Play, Pause, Upload, Trash2, Loader2, AlertCircle } from "lucide-react";
import { apiClient } from "../App";

/**
 * Browser native voice recorder using MediaRecorder API.
 * On stop, uploads the WebM blob to GridFS via /api/studio/uploads/voiceover
 * and calls onUploaded({ url, id, size }) with the public URL the render
 * pipeline can stream from.
 *
 * Three states wired into a compact pill UI:
 *   idle    → "Record your voice" button + Hint
 *   recording → live MM:SS timer + Stop button
 *   recorded → preview audio + Use this / Re-record / Delete
 */
export default function VoiceRecorder({ onUploaded, currentUrl, onClear }) {
  const [state, setState] = useState("idle"); // idle | recording | recorded | uploading
  const [seconds, setSeconds] = useState(0);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [blob, setBlob] = useState(null);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const audioElRef = useRef(null);

  const fmt = (s) => {
    const m = Math.floor(s / 60).toString().padStart(2, "0");
    const sec = Math.floor(s % 60).toString().padStart(2, "0");
    return `${m}:${sec}`;
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startRecording = async () => {
    setError("");
    if (typeof window === "undefined" || !navigator.mediaDevices || !window.MediaRecorder) {
      setError("Your browser doesn't support voice recording. Try Chrome or Edge.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 44100 },
      });
      streamRef.current = stream;
      // Prefer webm/opus (universal browser support + good quality at 1 mbps).
      let mimeType = "audio/webm;codecs=opus";
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        mimeType = "audio/webm";
        if (!MediaRecorder.isTypeSupported(mimeType)) mimeType = "";
      }
      const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = mr;
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = () => {
        const finalBlob = new Blob(chunksRef.current, { type: mr.mimeType || "audio/webm" });
        const url = URL.createObjectURL(finalBlob);
        setBlob(finalBlob);
        setPreviewUrl(url);
        setState("recorded");
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((t) => t.stop());
          streamRef.current = null;
        }
      };
      mr.start();
      setState("recording");
      setSeconds(0);
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch (e) {
      const msg = (e?.message || "").toString().toLowerCase();
      if (msg.includes("permission") || msg.includes("denied")) {
        setError("Microphone permission denied. Allow microphone access in your browser settings.");
      } else if (msg.includes("notfound") || msg.includes("not found")) {
        setError("No microphone detected. Plug one in and try again.");
      } else {
        setError("Could not start recording: " + (e?.message || "unknown error"));
      }
      setState("idle");
    }
  };

  const stopRecording = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
  };

  const resetRecording = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setBlob(null);
    setSeconds(0);
    setError("");
    setPlaying(false);
    setState("idle");
  };

  const togglePreview = () => {
    if (!audioElRef.current) return;
    if (playing) {
      audioElRef.current.pause();
      setPlaying(false);
    } else {
      audioElRef.current.play().catch(() => {});
      setPlaying(true);
    }
  };

  const uploadRecording = async () => {
    if (!blob) return;
    setState("uploading");
    setError("");
    try {
      const ext = (blob.type.includes("mp4") ? "m4a" : "webm");
      const form = new FormData();
      form.append("file", blob, `recording.${ext}`);
      const r = await apiClient.post("/studio/uploads/voiceover", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if (onUploaded) onUploaded(r.data);
      // Leave state on "recorded" so user can re-record if needed.
      setState("recorded");
    } catch (e) {
      setError(e?.response?.data?.detail || "Upload failed. Try again.");
      setState("recorded");
    }
  };

  // If parent says we already have a voiceover saved (currentUrl), show a
  // compact "saved" pill instead of the full recorder. User can clear it.
  if (currentUrl && state === "idle") {
    return (
      <div className="voice-recorder voice-recorder-saved" data-testid="voice-recorder-saved">
        <div className="voice-recorder-pill">
          <Mic size={14} />
          <span className="voice-recorder-saved-label">Custom voiceover saved</span>
        </div>
        <button
          type="button"
          className="voice-recorder-btn is-ghost"
          data-testid="voice-recorder-clear"
          onClick={() => onClear && onClear()}
          title="Remove your custom voiceover"
        >
          <Trash2 size={12} /> Remove
        </button>
      </div>
    );
  }

  return (
    <div className="voice-recorder" data-testid="voice-recorder">
      {state === "idle" && (
        <>
          <button
            type="button"
            className="voice-recorder-btn is-primary"
            data-testid="voice-recorder-start"
            onClick={startRecording}
          >
            <Mic size={14} /> Record your voice
          </button>
          <span className="voice-recorder-hint">
            Use your real voice instead of AI TTS — up to 25MB / ~10 minutes.
          </span>
        </>
      )}
      {state === "recording" && (
        <>
          <div className="voice-recorder-pulse" aria-hidden="true" />
          <span className="voice-recorder-timer" data-testid="voice-recorder-timer">
            {fmt(seconds)}
          </span>
          <button
            type="button"
            className="voice-recorder-btn is-danger"
            data-testid="voice-recorder-stop"
            onClick={stopRecording}
          >
            <Square size={12} fill="currentColor" /> Stop
          </button>
        </>
      )}
      {(state === "recorded" || state === "uploading") && previewUrl && (
        <>
          <button
            type="button"
            className="voice-recorder-btn is-ghost"
            data-testid="voice-recorder-play"
            onClick={togglePreview}
          >
            {playing ? <Pause size={12} /> : <Play size={12} />}
            {playing ? "Pause" : "Play"}
          </button>
          <audio
            ref={audioElRef}
            src={previewUrl}
            onEnded={() => setPlaying(false)}
            preload="auto"
            style={{ display: "none" }}
          />
          <span className="voice-recorder-timer">{fmt(seconds)}</span>
          <button
            type="button"
            className="voice-recorder-btn is-primary"
            data-testid="voice-recorder-upload"
            onClick={uploadRecording}
            disabled={state === "uploading"}
          >
            {state === "uploading" ? <Loader2 size={12} className="spin" /> : <Upload size={12} />}
            {state === "uploading" ? "Uploading…" : "Use this"}
          </button>
          <button
            type="button"
            className="voice-recorder-btn is-ghost"
            data-testid="voice-recorder-reset"
            onClick={resetRecording}
            disabled={state === "uploading"}
          >
            <Trash2 size={12} /> Re-record
          </button>
        </>
      )}
      {error && (
        <div className="voice-recorder-error" data-testid="voice-recorder-error">
          <AlertCircle size={12} /> {error}
        </div>
      )}
    </div>
  );
}
