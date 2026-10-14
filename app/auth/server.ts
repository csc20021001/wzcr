import { env } from 'cloudflare:workers';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { ensureDatabase, getD1 } from '@/db';
import { safeEqual, sanitizeReturnTo } from './security.mjs';

export { safeEqual, sanitizeReturnTo };

export const SESSION_COOKIE = 'campus_session';
export const OAUTH_STATE_COOKIE = 'campus_oauth_state';
export const OAUTH_VERIFIER_COOKIE = 'campus_oauth_verifier';
export const OAUTH_RETURN_COOKIE = 'campus_oauth_return';

const googleJwks = createRemoteJWKSet(new URL('https://www.googleapis.com/oauth2/v3/certs'));
const encoder = new TextEncoder();

type RuntimeEnv = {
  GOOGLE_CLIENT_ID?: string;
  GOOGLE_CLIENT_SECRET?: string;
  GOOGLE_REDIRECT_URI?: string;
};

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  avatarUrl: string | null;
};

export type GoogleConfig = {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
};

function runtimeValue(key: keyof RuntimeEnv) {
  const workerEnv = env as unknown as RuntimeEnv;
  return workerEnv[key]?.trim() || process.env[key]?.trim() || '';
}

export function getGoogleConfig(request: Request): GoogleConfig | null {
  const clientId = runtimeValue('GOOGLE_CLIENT_ID');
  const clientSecret = runtimeValue('GOOGLE_CLIENT_SECRET');
  if (!clientId || !clientSecret) return null;
  const redirectUri = runtimeValue('GOOGLE_REDIRECT_URI') || new URL('/api/auth/google/callback', request.url).toString();
  return { clientId, clientSecret, redirectUri };
}

export function isGoogleConfigured(request: Request) {
  return getGoogleConfig(request) !== null;
}

function base64Url(bytes: Uint8Array) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function randomToken(size = 32) {
  return base64Url(crypto.getRandomValues(new Uint8Array(size)));
}

export async function sha256Base64Url(value: string) {
  return base64Url(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(value))));
}

export function secureCookie(request: Request) {
  return new URL(request.url).protocol === 'https:';
}

export async function verifyGoogleIdToken(idToken: string, clientId: string) {
  const { payload } = await jwtVerify(idToken, googleJwks, {
    issuer: ['https://accounts.google.com', 'accounts.google.com'],
    audience: clientId,
  });
  if (!payload.sub || typeof payload.email !== 'string' || payload.email_verified !== true) {
    throw new Error('Google account is missing a verified email.');
  }
  return {
    sub: payload.sub,
    email: payload.email,
    name: typeof payload.name === 'string' && payload.name.trim() ? payload.name.trim() : payload.email.split('@')[0],
    avatarUrl: typeof payload.picture === 'string' ? payload.picture : null,
  };
}

function cookieValue(request: Request, name: string) {
  const cookies = request.headers.get('cookie') ?? '';
  for (const part of cookies.split(';')) {
    const [key, ...value] = part.trim().split('=');
    if (key === name) return decodeURIComponent(value.join('='));
  }
  return null;
}

export async function createSession(userId: string) {
  await ensureDatabase();
  const token = randomToken(32);
  const id = await sha256Base64Url(token);
  const createdAt = new Date().toISOString();
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString();
  await getD1().prepare(`
    INSERT INTO auth_sessions (id, user_id, expires_at, created_at)
    VALUES (?, ?, ?, ?)
  `).bind(id, userId, expiresAt, createdAt).run();
  return { token, expiresAt };
}

export async function getSessionUser(request: Request): Promise<AuthUser | null> {
  const token = cookieValue(request, SESSION_COOKIE);
  if (!token) return null;
  await ensureDatabase();
  const id = await sha256Base64Url(token);
  const now = new Date().toISOString();
  return getD1().prepare(`
    SELECT u.id, u.email, u.name, u.avatar_url
    FROM auth_sessions s
    JOIN users u ON u.id = s.user_id
    WHERE s.id = ? AND s.expires_at > ?
    LIMIT 1
  `).bind(id, now).first<AuthUser & { avatar_url: string | null }>().then((row) => row ? ({
    id: row.id,
    email: row.email,
    name: row.name,
    avatarUrl: row.avatar_url,
  }) : null);
}

export async function deleteSession(request: Request) {
  const token = cookieValue(request, SESSION_COOKIE);
  if (!token) return;
  await ensureDatabase();
  await getD1().prepare('DELETE FROM auth_sessions WHERE id = ?').bind(await sha256Base64Url(token)).run();
}

export function isSameOriginRequest(request: Request) {
  const origin = request.headers.get('origin');
  return !origin || origin === new URL(request.url).origin;
}
