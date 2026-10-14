import { NextRequest, NextResponse } from 'next/server';
import {
  getGoogleConfig,
  OAUTH_RETURN_COOKIE,
  OAUTH_STATE_COOKIE,
  OAUTH_VERIFIER_COOKIE,
  randomToken,
  sanitizeReturnTo,
  secureCookie,
  sha256Base64Url,
} from '@/app/auth/server';

export async function GET(request: NextRequest) {
  const config = getGoogleConfig(request);
  if (!config) return NextResponse.redirect(new URL('/?authError=not-configured', request.url));

  const state = randomToken(24);
  const verifier = randomToken(48);
  const challenge = await sha256Base64Url(verifier);
  const returnTo = sanitizeReturnTo(request.nextUrl.searchParams.get('returnTo'));
  const authorizationUrl = new URL('https://accounts.google.com/o/oauth2/v2/auth');
  authorizationUrl.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    prompt: 'select_account',
  }).toString();

  const response = NextResponse.redirect(authorizationUrl);
  const cookieOptions = { httpOnly: true, secure: secureCookie(request), sameSite: 'lax' as const, path: '/', maxAge: 600 };
  response.cookies.set(OAUTH_STATE_COOKIE, state, cookieOptions);
  response.cookies.set(OAUTH_VERIFIER_COOKIE, verifier, cookieOptions);
  response.cookies.set(OAUTH_RETURN_COOKIE, returnTo, cookieOptions);
  return response;
}
