# F2F48 Studio — Test credentials

## Auth (v1.19.0 magic-link required for all non-dev accounts)

As of v1.19.0 (2026-07-01) the app uses **passwordless magic-link auth**.
Users enter their email at `/login` → we generate a 15-minute single-use
token, push an outbound webhook to GoHighLevel (GHL) → GHL's workflow
sends the actual email → user clicks the link → we verify + issue JWT.

### DEV_BYPASS (preview/local only)
The backend `DEV_BYPASS_EMAIL` env var still short-circuits the magic
link flow for local testing. Only this single email works via the
legacy `/api/auth/check` endpoint:

- **Email**: `drcharitycampbell@gmail.com`
- **Password**: (none — DEV_BYPASS bypasses magic link entirely)
- **How to use**: POST `/api/auth/check` with `{"email": "drcharitycampbell@gmail.com"}` — returns JWT directly

This email is **also in ADMIN_EMAILS**, so the issued JWT has `isAdmin=true`.
This grants access to the `/admin` route and the `/api/admin/*` endpoints.

### Non-admin test user (STUDIO_GRANT — requires magic link)

Founder-tier grant email:
- **Email**: `directkynections@gmail.com` (in STUDIO_GRANT_EMAILS but not ADMIN_EMAILS)
- **Password**: (none — magic-link only)
- **How to sign in**:
  1. POST `/api/auth/request-magic-link` with `{"email": "directkynections@gmail.com"}`
  2. Retrieve the magic link from backend logs (`tail /var/log/supervisor/backend.*.log | grep magic-link`) — since GHL_WEBHOOK_URL is empty in preview, links are logged to stdout as a fallback.
  3. Open the link in the browser (or `curl -i` it) — returns a 302 redirect to `/auth/callback#jwt=...&email=...`

### Magic-link testing endpoint (bypass GHL for automated tests)
For testing agents, use the DEV_BYPASS_EMAIL path via `/api/auth/check`
directly — it skips the whole magic-link loop and returns a JWT
immediately. No email delivery required.

## Magic-link flow endpoints

- **POST** `/api/auth/request-magic-link` `{email}` → `{ok:true, sent:true}` (anti-enumeration; always same response)
- **GET**  `/api/auth/verify-magic-link?token=<token>` → 302 redirect to `<origin>/auth/callback#jwt=<JWT>&email=<email>`
- **POST** `/api/auth/check` `{email}` — DEV_BYPASS_EMAIL only, 403 for anything else
- **GET**  `/api/auth/me` — validates JWT, returns user object

## AppSumo webhook

- **URL**: `POST /api/appsumo-webhook`
- **Auth**: HMAC SHA256 via `X-Appsumo-Signature` + `X-Appsumo-Timestamp`
  headers, using `APPSUMO_LICENSING_KEY` as the shared secret. HMAC is
  a no-op when the key is empty (pre-launch behavior).
- **Validation ping** (test:true payload) → returns `{event, success:true}` HTTP 200
- **Real events** — processed against `db.appsumo_licenses` (keyed by
  license_key) and `db.buyers` (keyed by email, when known).
- **OAuth Redirect URL**: `GET /api/appsumo/oauth/redirect` — returns 200 for validation, 302 to `/redeem?appsumo_code=<code>` for real activations.

## Admin panel test data

Run `python /app/backend/tests/seed_admin_dev_data.py` to seed:
- 6 sample buyers (alex.morgan@example.com, jamie.lin@example.com, etc.)
- 5 activity rows (including 1 `webhook_failed` for the Replay button)

## Pinball webhook (Phase C)

- **Token env var**: `PINBALL_WEBHOOK_TOKEN` in `/app/backend/.env`
- **Endpoint**: `POST /api/pinball-webhook?token=<TOKEN>&product=<base|shorts|studio>`
- **Body**: `{"email": "...", "total_amount": "<cents-as-string>", "order_id": "..."}`

## Notes
- JWT-based session: token returned by `/api/auth/verify-magic-link` (via URL fragment on callback) is stored in localStorage as `f48_studio_token` and sent as `Authorization: Bearer …`.
- The JWT carries an `isAdmin` claim sourced from ADMIN_EMAILS env var.
- All `/api/studio/*` endpoints require this JWT + `studio` entitlement.
- All `/api/admin/*` endpoints require `isAdmin=true` on the JWT.
- Magic-link tokens live in `db.magic_link_tokens` with a 15-min TTL index — expired tokens auto-purge.
