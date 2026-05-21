import { clearSessionCookie } from './_shared/auth.mjs';

export const handler = async () => ({
  statusCode: 200,
  headers: {
    'Content-Type': 'application/json',
    'Set-Cookie': clearSessionCookie(),
  },
  body: JSON.stringify({ ok: true }),
});
