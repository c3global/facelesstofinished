import { readSession, readCookies, json } from './_shared/auth.mjs';
import { listEntitlements } from './_shared/store.mjs';
import { isAdminEmail } from './_shared/admin.mjs';

export default async (req) => {
  const session = readSession(readCookies(req));
  if (!session) return json({ authenticated: false }, { status: 401 });
  const entitlements = await listEntitlements(session.email).catch(() => []);
  const isAdmin = isAdminEmail(session.email);
  return json({ authenticated: true, email: session.email, entitlements, isAdmin });
};
