# AI Script Engine

A branded tool for **C3 Global** that generates complete faceless YouTube video scripts from a topic or keyword. Lives at `sprint.c3global.co/faceless`.

Built with React + Vite. Calls the Anthropic API directly from the browser.

---

## Local setup

```bash
npm install
cp .env.example .env
# add your key:
# VITE_ANTHROPIC_API_KEY=sk-ant-...
npm run dev
```

Then visit http://localhost:5173/faceless

## Build

```bash
npm run build
npm run preview
```

## Deploying to Netlify

1. Push this repo to GitHub.
2. In Netlify: **Add new site → Import from Git** and select the repo.
3. Build settings are auto-detected from `netlify.toml`:
   - Build command: `npm run build`
   - Publish directory: `dist`
4. Under **Site settings → Environment variables**, add:
   - `VITE_ANTHROPIC_API_KEY` = your Anthropic API key
5. Deploy. The included `_redirects` + `netlify.toml` handle SPA routing so `/faceless` resolves correctly on refresh.
6. To serve at `sprint.c3global.co/faceless`, point that subdomain at the Netlify site under **Domain management**.

## Notes

- The Anthropic SDK is called client-side with `dangerouslyAllowBrowser: true`. The API key ships in the bundle — only use this pattern on a gated/internal deployment, or proxy through a serverless function for production.
- Model: `claude-sonnet-4-20250514`, max tokens 2000.
