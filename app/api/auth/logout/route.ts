import { NextResponse } from 'next/server';
import { deleteSession, isSameOriginRequest, secureCookie, SESSION_COOKIE } from '@/app/auth/server';

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) return NextResponse.json({ error: '不允許跨站登出。' }, { status: 403 });
  await deleteSession(request);
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    secure: secureCookie(request),
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  });
  return response;
}
