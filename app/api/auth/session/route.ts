import { NextResponse } from 'next/server';
import { getSessionUser, isGoogleConfigured } from '@/app/auth/server';

export async function GET(request: Request) {
  return NextResponse.json({
    user: await getSessionUser(request),
    googleConfigured: isGoogleConfigured(request),
  }, { headers: { 'Cache-Control': 'no-store' } });
}
