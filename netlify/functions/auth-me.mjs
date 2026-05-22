import { readSession, readCookies, json } from './_shared/auth.mjs';

export default async (req) => {
  const session = readSession(readCookies(req));
  if (!session) return json({ authenticated: false }, { status: 401 });
  return json({ authenticated: true, email: session.email });
};
