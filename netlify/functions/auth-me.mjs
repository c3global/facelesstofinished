import { readSession, readCookies, json } from './_shared/auth.mjs';
import { listEntitlements } from './_shared/store.mjs';

export default async (req) => {
  const session = readSession(readCookies(req));
  if (!session) return json({ authenticated: false }, { status: 401 });
  const entitlements = await listEntitlements(session.email).catch(() => []);
  return json({ authenticated: true, email: session.email, entitlements });
};
