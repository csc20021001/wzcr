import { NextResponse } from 'next/server';
import { ensureDatabase } from '@/db';
import { listDepartments } from '@/db/departments';

export async function GET(request: Request) {
  const universityId = new URL(request.url).searchParams.get('university_id')?.trim() ?? '';
  if (!/^[a-z0-9-]{2,20}$/.test(universityId)) {
    return NextResponse.json({ error: '學校代碼格式不正確。' }, { status: 400 });
  }
  await ensureDatabase();
  return NextResponse.json({ departments: await listDepartments(universityId) }, {
    headers: { 'Cache-Control': 'public, max-age=300, s-maxage=3600' },
  });
}
