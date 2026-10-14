import { NextResponse } from 'next/server';
import { ensureDatabase } from '@/db';
import { getCourse } from '@/db/courses';

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  await ensureDatabase();
  const course = await getCourse(id);
  if (!course) return NextResponse.json({ error: '找不到課程資料。' }, { status: 404 });
  return NextResponse.json({ course });
}
