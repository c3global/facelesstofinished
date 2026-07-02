import { useEffect } from "react";
import { PLATFORMS, MODES } from "../components/scripts/scriptsConstants";

/**
 * Mirrors the active Shorts platform onto:
 *   - `--platform-accent` (the brand color used by tag/CTA gradients)
 *   - `documentElement[data-platform]` (so global CTAs like
 *     `.cta-btn.is-platform` can target [data-platform="tiktok"] to flip
 *     foreground ink to dark, since white text disappears on TikTok cyan)
 *
 * The effect is a no-op outside Shorts mode and cleans up its attribute
 * when the user leaves the mode or unmounts.
 *
 * Returns nothing — pure side-effect hook.
 */
export function usePlatformAccent(mode, platform, outputPlatform) {
  useEffect(() => {
    const root = document.documentElement;
    if (mode === MODES.SHORTS) {
      const activeId = outputPlatform || platform;
      const p = PLATFORMS.find((x) => x.id === activeId);
      if (p) {
        root.style.setProperty("--platform-accent", p.accent);
        root.setAttribute("data-platform", activeId);
      }
    } else {
      root.style.removeProperty("--platform-accent");
      root.removeAttribute("data-platform");
    }
  }, [mode, platform, outputPlatform]);
}
