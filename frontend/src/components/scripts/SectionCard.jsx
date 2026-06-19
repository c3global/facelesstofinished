import React, { useState } from "react";
import { Copy, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { renderToStaticMarkup } from "react-dom/server";
import remarkGfm from "remark-gfm";

export const SECTION_LABEL = {
  angles: "Topic Angles", concept: "Video Concept", hooks: "Hook Variations",
  outline: "Outline", script: "Narration Script", transitions: "Transitions",
  broll: "B-Roll Shot List", notes: "Production Notes",
  shortScript: "Short-Form Script", onScreen: "On-Screen Text",
  caption: "Caption", hashtags: "Hashtags",
  titleVariants: "Title / Thumbnail Variants", coverPrompts: "Cover Image Prompts",
};

// Regex that captures a bracketed B-roll cue like [B-ROLL: pouring espresso].
const BROLL_RE = /\[B-ROLL:[^\]]*\]/gi;
// Regex for narration scene headers like [HOOK — 0:00–0:30] or
// [INTRO BRIDGE — 0:30–1:00]. Match all-caps text inside brackets followed
// optionally by an em-dash and timecode. Excludes B-ROLL so they don't double-match.
const SCENE_HEADER_RE = /^\s*\[(?!B-ROLL)([A-Z0-9 +,&'#–—\-:]{2,}(?:\s*[—-]\s*\d[\d:–\- ]*)?)\]\s*$/;

// Wrap B-roll cues in styled spans inside any inline children. Walks the
// children array; for each string, splits on BROLL_RE and wraps matches.
// `inlineStyle` controls whether the inline CSS for clipboard-friendly
// rendering is applied (true) — defaults to false so the on-screen
// version uses CSS classes from App.css.
function wrapBrollInChildren(children, inlineStyle = false) {
  return React.Children.toArray(children).flatMap((child, i) => {
    if (typeof child !== "string") return [child];
    const parts = child.split(BROLL_RE);
    const matches = child.match(BROLL_RE) || [];
    const out = [];
    parts.forEach((part, idx) => {
      if (part) out.push(part);
      if (matches[idx]) {
        out.push(
          inlineStyle ? (
            <span
              key={`broll-${i}-${idx}`}
              className="broll-cue"
              style={{
                color: "#1D9E75",
                fontFamily:
                  "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontWeight: 600,
              }}
            >
              {matches[idx]}
            </span>
          ) : (
            <span key={`broll-${i}-${idx}`} className="broll-cue">
              {matches[idx]}
            </span>
          )
        );
      }
    });
    return out;
  });
}

// Recursively pull plain text out of React children — handles strings,
// arrays, and elements with .props.children. Used by the scene-header
// detector below since Claude often emits headers wrapped in **bold**
// (which becomes a nested <strong> element, not a top-level string).
function extractText(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node.props && node.props.children !== undefined) return extractText(node.props.children);
  return "";
}

const mdComponents = {
  p({ node, children, ...props }) {
    // Detect a scene-header paragraph (bracketed all-caps), promote to
    // styled h-mini. Works even when Claude wraps it in **bold**.
    const text = extractText(children).trim();
    if (SCENE_HEADER_RE.test(text)) {
      return <p className="scene-header" {...props}>{text}</p>;
    }
    return <p {...props}>{wrapBrollInChildren(children)}</p>;
  },
  li({ node, children, ...props }) {
    // Unconditional: if any child is a <p>-like wrapper, hoist its inner
    // children up so '1.' + content render on a single line. react-markdown
    // v10 turns single-paragraph li-children into a <p> by default — this
    // strips that wrapper everywhere it appears.
    const out = React.Children.toArray(children).flatMap((c) => {
      if (typeof c === "string") return [c];
      if (React.isValidElement(c)) {
        const isPara =
          c.type === "p" ||
          c.props?.node?.type === "paragraph" ||
          // Our overridden <p> renders as a real <p> too. Detect by checking
          // for the className the override sets (none on plain paragraphs).
          (c.props?.className == null && c.props?.children != null);
        if (isPara) return React.Children.toArray(c.props.children);
      }
      return [c];
    });
    return <li {...props}>{wrapBrollInChildren(out)}</li>;
  },
};

// Clipboard variant of mdComponents: identical structure, but injects
// inline CSS on every styled element so Google Docs / Notion / Word
// preserve B-roll green + scene-header accent on paste. (External apps
// strip class-based CSS but honor inline styles.)
const mdComponentsInline = {
  p({ node, children, ...props }) {
    const text = extractText(children).trim();
    if (SCENE_HEADER_RE.test(text)) {
      return (
        <p
          className="scene-header"
          style={{
            color: "#C9956C",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            borderBottom: "1px solid rgba(201,149,108,0.35)",
            paddingBottom: "4px",
            marginTop: "14px",
          }}
          {...props}
        >
          {text}
        </p>
      );
    }
    return <p {...props}>{wrapBrollInChildren(children, true)}</p>;
  },
  li({ node, children, ...props }) {
    const out = React.Children.toArray(children).flatMap((c) => {
      if (typeof c === "string") return [c];
      if (React.isValidElement(c)) {
        const isPara =
          c.type === "p" ||
          c.props?.node?.type === "paragraph" ||
          (c.props?.className == null && c.props?.children != null);
        if (isPara) return React.Children.toArray(c.props.children);
      }
      return [c];
    });
    return <li {...props}>{wrapBrollInChildren(out, true)}</li>;
  },
};

// Convert section markdown → HTML string for the clipboard's text/html slot.
// Uses the INLINE-STYLED ReactMarkdown configuration so what the user
// pastes into Google Docs / Notion / Word preserves the B-roll green
// and scene-header accent colors. (External apps strip class-based CSS
// but honor inline `style="..."` attributes.)
function markdownToHtml(md) {
  try {
    return renderToStaticMarkup(
      <div>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponentsInline}>
          {md}
        </ReactMarkdown>
      </div>
    );
  } catch {
    return `<pre>${(md || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")}</pre>`;
  }
}

// Best-effort dual-format clipboard write. Falls back to plain-text on
// browsers that don't support ClipboardItem (older Safari, Firefox <94).
async function copyRichText(plain, html) {
  try {
    if (window.ClipboardItem && navigator.clipboard?.write) {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": new Blob([plain], { type: "text/plain" }),
          "text/html": new Blob([html], { type: "text/html" }),
        }),
      ]);
      return true;
    }
    await navigator.clipboard.writeText(plain);
    return true;
  } catch {
    try {
      await navigator.clipboard.writeText(plain);
      return true;
    } catch {
      return false;
    }
  }
}

export function CopyButton({ text, html, testid }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy-btn"
      data-testid={testid}
      onClick={async (e) => {
        e.stopPropagation();
        const richHtml = html || markdownToHtml(text);
        const ok = await copyRichText(text, richHtml);
        if (ok) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }
      }}
    >
      <Copy size={12} /> {copied ? "Copied!" : "Copy"}
    </button>
  );
}

/**
 * SectionCard — collapsible script section (v1.8.0 mirror).
 *
 * Clicking the header collapses/expands the body. Collapsed state is OWNED
 * by the parent (`collapsed` prop + `onToggle` callback) so the global
 * "Collapse all / Expand all" toggle in the sticky nav bar can flip every
 * card at once. Body is preserved while collapsed — no markdown re-render
 * cost when the user toggles it back open.
 */
export function SectionCard({ keyName, section, testid, revealIndex, collapsed = false, onToggle }) {
  if (!section) return null;
  const style = revealIndex != null ? { animationDelay: `${revealIndex * 90}ms` } : undefined;
  const headerProps = onToggle
    ? {
        role: "button",
        tabIndex: 0,
        onClick: () => onToggle(keyName),
        onKeyDown: (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle(keyName);
          }
        },
        "aria-expanded": !collapsed,
      }
    : {};
  return (
    <section
      id={`section-${keyName}`}
      className={`section-card${revealIndex != null ? " section-card-reveal" : ""}${collapsed ? " is-collapsed" : ""}`}
      data-testid={testid}
      data-section={keyName}
      style={style}
    >
      <header
        className={`section-card-head${onToggle ? " is-clickable" : ""}`}
        data-testid={`${testid}-header`}
        {...headerProps}
      >
        <div className="section-card-head-left">
          {onToggle && (
            <ChevronDown
              size={14}
              className={`section-card-chevron${collapsed ? " is-collapsed" : ""}`}
              aria-hidden="true"
            />
          )}
          <h3 className="section-card-title">{SECTION_LABEL[keyName] || section.title}</h3>
        </div>
        <CopyButton text={section.body} testid={`${testid}-copy`} />
      </header>
      {!collapsed && (
        <div className="section-card-body markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {section.body}
          </ReactMarkdown>
        </div>
      )}
    </section>
  );
}

export function SkeletonCard({ keyName }) {
  return (
    <section className="section-card section-card-skeleton" data-testid={`skeleton-${keyName}`} aria-hidden="true">
      <header className="section-card-head"><div className="skeleton-bar skeleton-bar-title" /></header>
      <div className="section-card-body">
        <div className="skeleton-bar" style={{ width: "92%" }} />
        <div className="skeleton-bar" style={{ width: "78%" }} />
        <div className="skeleton-bar" style={{ width: "85%" }} />
        <div className="skeleton-bar" style={{ width: "60%" }} />
      </div>
    </section>
  );
}

// Re-export the markdown→HTML helper so the "Copy full script" button in
// Scripts.jsx can write rich HTML alongside plain text.
export { markdownToHtml, copyRichText };
