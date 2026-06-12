import { clearSessionCookie, json } from './_shared/auth.mjs';

export default async () => json({ ok: true }, {
  headers: { 'Set-Cookie': clearSessionCookie() },
});
