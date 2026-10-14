import { NextRequest, NextResponse } from 'next/server';
import { ensureDatabase, getD1 } from '@/db';
import {
  createSession,
  getGoogleConfig,
  OAUTH_RETURN_COOKIE,
  OAUTH_STATE_COOKIE,
  OAUTH_VERIFIER_COOKIE,
  safeEqual,
  sanitizeReturnTo,
  secureCookie,
  SESSION_COOKIE,
  verifyGoogleIdToken,
} from '@/app/auth/server';

function clearOAuthCookies(response: NextResponse, request: Request) {
  const options = { httpOnly: true, secure: secureCookie(request), sameSite: 'lax' as const, path: '/', maxAge: 0 };
  response.cookies.set(OAUTH_STATE_COOKIE, '', options);
  response.cookies.set(OAUTH_VERIFIER_COOKIE, '', options);
  response.cookies.set(OAUTH_RETURN_COOKIE, '', options);
}

function errorRedirect(request: NextRequest, code: string) {
  const response = NextResponse.redirect(new URL(`/?authError=${encodeURIComponent(code)}`, request.url));
  clearOAuthCookies(response, request);
  return response;
}

export async function GET(request: NextRequest) {
  const config = getGoogleConfig(request);
  const code = request.nextUrl.searchParams.get('code');
  const state = request.nextUrl.searchParams.get('state');
  const storedState = request.cookies.get(OAUTH_STATE_COOKIE)?.value ?? '';
  const verifier = request.cookies.get(OAUTH_VERIFIER_COOKIE)?.value ?? '';
  if (!config || !code || !state || !storedState || !verifier || !safeEqual(state, storedState)) {
    return errorRedirect(request, 'invalid-state');
  }

  try {
    const tokenResponse = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        code,
        client_id: config.clientId,
        client_secret: config.clientSecret,
        redirect_uri: config.redirectUri,
        grant_type: 'authorization_code',
        code_verifier: verifier,
      }),
    });
    if (!tokenResponse.ok) return errorRedirect(request, 'token-exchange');
    const tokenData = await tokenResponse.json() as { id_token?: string };
    if (!tokenData.id_token) return errorRedirect(request, 'missing-id-token');

    const profile = await verifyGoogleIdToken(tokenData.id_token, config.clientId);
    await ensureDatabase();
    const db = getD1();
    const existing = await db.prepare('SELECT id FROM users WHERE google_sub = ? LIMIT 1').bind(profile.sub).first<{ id: string }>();
    const userId = existing?.id ?? crypto.randomUUID();
    const now = new Date().toISOString();
    await db.prepare(`
      INSERT INTO users (id, google_sub, email, name, avatar_url, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(google_sub) DO UPDATE SET
        email = excluded.email,
        name = excluded.name,
        avatar_url = excluded.avatar_url,
        updated_at = excluded.updated_at
    `).bind(userId, profile.sub, profile.email, profile.name, profile.avatarUrl, now, now).run();

    const session = await createSession(userId);
    const returnTo = sanitizeReturnTo(request.cookies.get(OAUTH_RETURN_COOKIE)?.value ?? '/');
    const response = NextResponse.redirect(new URL(returnTo, request.url));
    response.cookies.set(SESSION_COOKIE, session.token, {
      httpOnly: true,
      secure: secureCookie(request),
      sameSite: 'lax',
      path: '/',
      expires: new Date(session.expiresAt),
    });
    clearOAuthCookies(response, request);
    return response;
  } catch {
    return errorRedirect(request, 'oauth-failed');
  }
}
