import { readSession, getCookieHeader } from './_shared/auth.mjs';

export const handler = async (event) => {
  const session = readSession(getCookieHeader(event));
  if (!session) {
    return {
      statusCode: 401,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ authenticated: false }),
    };
  }
  return {
    statusCode: 200,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ authenticated: true, email: session.email }),
  };
};
