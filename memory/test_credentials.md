# F2F48 Studio — Test credentials

## Auth (DEV_BYPASS path, used during preview)

The backend has a `DEV_BYPASS_EMAIL` env var that grants all entitlements
(`base`, `shorts`, `studio`) for testing without hitting the live Netlify
auth endpoint. Set in `/app/backend/.env`:

- **Email:** `drcharitycampbell@gmail.com`
- **Password:** (none — passwordless login; just submit the email)

This email is **also in ADMIN_EMAILS**, so the issued JWT has `isAdmin=true`.
This grants access to the new `/admin` route and the `/api/admin/*` endpoints.

For a **non-admin** test user (entitlement-only, no admin), use:
- **Email:** `directkynections@gmail.com` (in STUDIO_GRANT_EMAILS but not ADMIN_EMAILS)

Any other email returns 401 unless the backend is configured with
`NETLIFY_AUTH_URL` AND the request includes a valid Netlify session cookie
in the `cookies` field of the `/api/auth/check` request body.

## Admin panel test data

Run `python /app/backend/tests/seed_admin_dev_data.py` to seed:
- 6 sample buyers (alex.morgan@example.com, jamie.lin@example.com, etc.)
- 5 activity rows (including 1 `webhook_failed` for the Replay button)

## Pinball webhook (Phase C)

- **Token env var**: `PINBALL_WEBHOOK_TOKEN` in `/app/backend/.env` (default placeholder: `replace-me-before-deploy`)
- **Endpoint**: `POST /api/pinball-webhook?token=<TOKEN>&product=<base|shorts|studio>`
- **Body**: `{"email": "...", "total_amount": "<cents-as-string>", "order_id": "..."}`
- **Behavior**: token-gated, dedupes by `order_id`, union-merges entitlements

## Notes
- JWT-based session: token returned by `/api/auth/check` is stored in
  localStorage as `f48_studio_token` and sent as `Authorization: Bearer …`.
- The JWT now carries an `isAdmin` claim sourced from ADMIN_EMAILS env var
  (falls back to Netlify `auth-me` response in production).
- All `/api/studio/*` endpoints require this JWT + `studio` entitlement.
- All `/api/admin/*` endpoints require `isAdmin=true` on the JWT.
