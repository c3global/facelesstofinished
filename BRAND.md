# Faceless to Finished — Brand & UI System

Reference document for matching the visual feel of the live build at **faceless48.c3global.co**. Hand this to anyone building UI that needs to look and feel consistent with the existing product.

---

## 1. Color System

### Base palette — dark mode (default)

```css
:root {
  --bg: #0F0A1E;                          /* page background */
  --surface: #1C1533;                     /* cards, inputs */
  --border: #3D3570;                      /* strong borders */
  --border-soft: rgba(61, 53, 112, 0.55); /* subtle dividers */
  --primary: #7F77DD;                     /* brand accent */
  --text: #E8E4FF;                        /* body text */
  --muted: #8B85B8;                       /* secondary text */
  --input-bg: #1C1533;
  --card-surface: rgba(255, 255, 255, 0.03);
  --card-surface-hover: rgba(255, 255, 255, 0.06);
  --header-bg: rgba(15, 10, 30, 0.6);
  --header-text: #E8E4FF;
  --header-border: rgba(61, 53, 112, 0.55);
}
```

### Base palette — light mode

```css
[data-theme="light"] {
  --bg: #F6F4FB;                              /* slightly purple-tinted, never pure white */
  --surface: #FFFFFF;
  --border: #D8D2EA;
  --border-soft: rgba(120, 110, 170, 0.25);
  --primary: #5E55C2;                         /* darker than dark-mode primary */
  --text: #1A1530;
  --muted: #5B5680;
  --input-bg: #FFFFFF;
  --card-surface: #FFFFFF;
  --card-surface-hover: #FAF8FF;
}
```

### Semantic / status colors (shared)

```css
--teal: #1D9E75;   /* success, completed */
--blue: #378ADD;   /* info, links */
--rose: #C9956C;   /* warning, highlight */
--red: #C41A18;    /* error, danger */
```

### Platform accents (Shorts mode only)

Each platform tints its UI elements (pill, phone-mockup chrome, CTA gradient) with its native brand color:

| Platform | Hex |
|---|---|
| YouTube Shorts | `#FF0033` |
| Instagram Reels | `#E1306C` |
| TikTok | `#25F4EE` |

### Sprint angle accents (Content Sprint mode)

Five angles in the Content Sprint feature each have a distinct accent for the chip and phone-card border:

| Angle | Hex |
|---|---|
| Curiosity | `#7F77DD` |
| Contrarian | `#C41A18` |
| How-To | `#1D9E75` |
| Story | `#E0A458` |
| List | `#378ADD` |

### Section card accents

Each section card uses a 3px-wide left border + colored title in its accent. Consistent across long-form and shorts modes where sections overlap.

| Section | Hex |
|---|---|
| Topic Angles | `#E0A458` |
| Video Concept | `#7F77DD` |
| Hook Variations | `#C41A18` |
| Outline | `#5BA0F2` |
| Full Script / Short-Form Script | `#1D9E75` |
| Transitions | `#9C6DD1` |
| B-Roll Shot List | `#378ADD` |
| Caption | `#5BA0F2` |
| Hashtags | `#9C6DD1` |
| On-Screen Text | `#7F77DD` |
| Title / Thumbnail Variants | `#E0A458` |
| Cover Image Prompts | `#E7B23C` |
| Production Notes | `#C9956C` |

---

## 2. Typography

### Font families

```css
/* Body — all UI text */
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
  'Helvetica Neue', Arial, sans-serif;

/* Brand wordmark only — "FACELESS 48" logo */
font-family: 'Arial Black', Arial, sans-serif;
```

Load Inter from Google Fonts. Always apply font smoothing:

```css
body {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  line-height: 1.55;
}
```

### Type scale

| Element | Size | Weight | Line height | Letter spacing |
|---|---|---|---|---|
| **Hero headline** | `clamp(36px, 6vw, 64px)` | 700 | 1.05 | -0.02em |
| **Hero sub** | 16px | 400 | 1.55 | 0 |
| **Section card title (eyebrow)** | 13px | 700 | 1.55 | **0.22em** UPPERCASE |
| **Card body** | 15px | 400 | 1.55 | 0 |
| **Card body — large (full script)** | 17px | 400 | **1.8** | 0.005em |
| **Body / default** | 16px | 400 | 1.55 | 0 |
| **Small / helper** | 12–13px | 600 | 1.4 | 0–0.02em |
| **Tiny labels / badges** | 10–11px | 600 | 1.3 | 0.06–0.1em |
| **Section eyebrows (large output)** | 22px | 800 | 1.05 | -0.01em |

### Weights actually used

Only four. Keep the system tight:
- **600** — buttons, chips, labels
- **700** — section eyebrows, hero headline
- **800** — output section headers ("Shorts Derived from Your Script")
- **900** — reserved for special emphasis only

---

## 3. Signature Treatments

These are the specific moves that make the design feel like itself rather than generic SaaS. **If you skip these, the page will look like every other tool.** If you nail them, everything else falls into place.

### A. Eyebrow uppercase tracking on section titles

```css
.card-title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}
```

Used on every section card title (Hook Variations, Outline, Script, etc.). The combination of small size + wide tracking + uppercase is what makes each card feel like a magazine section instead of a form field.

### B. Hero gradient text

```css
.hero-headline {
  font-size: clamp(36px, 6vw, 64px);
  font-weight: 700;
  line-height: 1.05;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, #FFFFFF 0%, #E8E4FF 35%, #C9956C 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
```

White → lavender → warm rose, 135-degree diagonal. The lavender-to-rose transition is what reads as "premium."

### C. Ambient aurora background

This is the single biggest visual differentiator. Three soft radial gradients painted just off-screen via a fixed pseudo-element:

```css
:root {
  --aurora-1: rgba(127, 119, 221, 0.22);  /* primary purple */
  --aurora-2: rgba(55, 138, 221, 0.16);   /* blue */
  --aurora-3: rgba(201, 149, 108, 0.10);  /* rose */
}

[data-theme="light"] {
  --aurora-1: rgba(127, 119, 221, 0.10);  /* ~50% softer in light mode */
  --aurora-2: rgba(55, 138, 221, 0.07);
  --aurora-3: rgba(201, 149, 108, 0.06);
}

body::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(900px 600px at 18% -10%, var(--aurora-1), transparent 60%),
    radial-gradient(800px 500px at 100% 15%, var(--aurora-2), transparent 65%),
    radial-gradient(700px 500px at 50% 110%, var(--aurora-3), transparent 60%);
}
```

Costs nothing performance-wise. Makes the page feel atmospheric rather than flat. **This is the highest-leverage detail in the entire system.**

### D. Section cards have a 3px colored left border

```css
.card {
  border: 1px solid var(--border-soft);
  border-left: 3px solid;          /* color set inline per section */
  border-radius: 14px;
  padding: 28px 30px;
  background: linear-gradient(180deg, var(--surface-2) 0%, var(--surface) 100%);
}
```

Set `border-left-color` to the section's accent color. This is the visual scannability backbone of the long-form output.

---

## 4. Spacing Scale

Loose 4-px rhythm. Values in actual use:

| Tier | Values | Where |
|---|---|---|
| Micro | 2, 4, 5, 6 px | Inline icons, chip internals |
| Small | 8, 10, 12 px | Button padding, small section gaps |
| Default | 14, 16, 18 px | Card vertical padding, input padding |
| Medium | 20, 22, 24 px | Card horizontal padding, section gaps |
| Large | 28, 36 px | Card vertical padding, hero spacing |
| Page | 56 px | `.main` vertical padding |

**Card padding:** `28px 30px` desktop, `22px 20px` mobile.
**Section card gap:** `14–16px` between cards in long-form output.

---

## 5. Border Radius Scale

| Use | Value |
|---|---|
| Pills / chips | `999px` |
| Circles / dots | `50%` |
| Inline badges, tags | `3–4px` |
| Small buttons | `6–8px` |
| Cards, primary buttons | `10–14px` |
| Large cards, modals | `16–24px` |
| Special / oversized | `36px` |

When in doubt: `12px` for cards, `999px` for chips.

---

## 6. Shadows / Elevation

```css
/* Card lift (light mode) */
box-shadow: 0 4px 16px rgba(127, 119, 221, 0.08);

/* Slightly heavier card (login, modals on light) */
box-shadow: 0 6px 24px rgba(127, 119, 221, 0.10);

/* Focus ring on interactive elements */
box-shadow: 0 0 0 2px rgba(127, 119, 221, 0.45);

/* Primary button hover glow */
box-shadow: 0 12px 30px -10px rgba(127, 119, 221, 0.55);

/* Platform card glow (Shorts mode) */
box-shadow: 0 18px 40px -10px color-mix(in srgb, var(--platform-accent, #C41A18) 50%, transparent),
            0 0 0 1px rgba(255,255,255,0.06) inset;

/* Modal overlay */
box-shadow: 0 12px 32px rgba(0,0,0,0.35);
```

**Rules:**
- Tint shadows with the brand purple at low opacity (`0.08–0.55`). Never use flat gray shadows.
- Use directional negative spread (`-10px`, `-20px`) for premium glows that taper rather than sit flat.

---

## 7. Animation Timings

| Use | Duration | Easing |
|---|---|---|
| Hover transitions (color, border) | 0.15–0.2s | `ease` |
| Collapse chevron rotation | 0.18s | `ease` |
| Section fade-up reveal | 0.25–0.3s | `ease both` |
| Modal appear | 0.3s | `ease` |
| Pulse / glow (generate button) | 1.5s | `infinite` |

Nothing animates longer than 0.3s unless it's an intentional ambient effect.

---

## 8. Implementation Priority

If you only have time to do 6 things from this document, do these in this order. They produce ~80% of the visual outcome:

1. **Load Inter from Google Fonts.** All UI text uses it.
2. **Implement the aurora background** (Section 3-C). Single biggest visual differentiator.
3. **Eyebrow uppercase tracking on section titles** (Section 3-A). The design's spine — `13px / 700 / 0.22em / uppercase`.
4. **Hero gradient text** (Section 3-B).
5. **Section cards with `border-radius: 14px` + 3px colored left border** matched to the section accent (Section 3-D).
6. **Section card padding `28px 30px` desktop, `22px 20px` mobile, gap `14–16px`** between cards.

The remaining tokens (spacing scale, radius scale, shadows, animations) provide consistency but won't make or break the visual feel on their own. Skip them only if the timeline is brutal.

---

## 9. Things to Avoid

- **Pure white surfaces in dark mode.** Always use the dark purples (`#1C1533`, `#0F0A1E`). Pure white reads as broken.
- **Pure black backgrounds.** Use `#0F0A1E` — deep purple, not `#000`. Flat black removes the brand warmth.
- **Heavy uppercase tracking on body text.** The 0.22em tracking is for eyebrow labels only — applying it to body text destroys readability.
- **Gray drop shadows.** Always tint with primary purple at low opacity. Gray reads as cheap.
- **Orange / amber gradients on primary CTAs.** The brand accent on buttons is purple (`#7F77DD` dark / `#5E55C2` light), not orange. Rose (`#C9956C`) is only used as a warm note in the hero gradient and for warning states.
- **Cartoonish or playful illustrations.** The aesthetic is calm, premium, "creator studio." Closer to Linear's dark mode than to a typical SaaS dashboard.

---

*Last updated against v1.8.0 of the live build (faceless48.c3global.co).*
