# F2F48 Studio — Test credentials

## Auth (DEV_BYPASS path, used during preview)

The backend has a `DEV_BYPASS_EMAIL` env var that grants all entitlements
(`base`, `shorts`, `studio`) for testing without hitting the live Netlify
auth endpoint. Set in `/app/backend/.env`:

- **Email:** `drcharitycampbell@gmail.com`
- **Password:** (none — passwordless login; just submit the email)

Any other email returns 401 unless the backend is configured with
`NETLIFY_AUTH_URL` AND the request includes a valid Netlify session cookie
in the `cookies` field of the `/api/auth/check` request body.

## Notes
- JWT-based session: token returned by `/api/auth/check` is stored in
  localStorage as `f48_studio_token` and sent as `Authorization: Bearer …`.
- All `/api/studio/*` endpoints require this JWT + `studio` entitlement.
