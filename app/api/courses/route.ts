import { NextResponse } from 'next/server';
import { getSessionUser, isSameOriginRequest } from '@/app/auth/server';
import { ensureDatabase } from '@/db';
import { getD1 } from '@/db';
import { getCourse, listCourses, makeCourseCardId } from '@/db/courses';
import { enforceUserRateLimit, RateLimitError } from '@/db/rate-limit';
import { validateCourseSubmission } from './validation.mjs';

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const universityId = params.get('university_id')?.trim() || undefined;
  const department = params.get('department')?.trim().slice(0, 80) || undefined;
  const search = params.get('search')?.trim().slice(0, 80) || undefined;
  const semester = params.get('semester')?.trim() || undefined;
  const limit = Number.parseInt(params.get('limit') || '36', 10);
  const offset = Number.parseInt(params.get('offset') || '0', 10);
  if (universityId && !/^[a-z0-9-]{2,20}$/.test(universityId)) {
    return NextResponse.json({ error: '學校代碼格式不正確。' }, { status: 400 });
  }
  if (semester && semester !== '1' && semester !== '2') {
    return NextResponse.json({ error: '學期只能是上學期或下學期。' }, { status: 400 });
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 60 || !Number.isInteger(offset) || offset < 0 || offset > 100000) {
    return NextResponse.json({ error: '分頁參數不正確。' }, { status: 400 });
  }
  await ensureDatabase();
  return NextResponse.json(await listCourses({ universityId, department, search, semester, limit, offset }), {
    headers: { 'Cache-Control': 'public, max-age=30, s-maxage=120' },
  });
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) return NextResponse.json({ error: '不允許跨站新增課程。' }, { status: 403 });
  const user = await getSessionUser(request);
  if (!user) return NextResponse.json({ error: '請先使用 Google 登入。' }, { status: 401 });
  try {
    await enforceUserRateLimit(user.id, 'course-submission', 8, 60);
  } catch (error) {
    if (error instanceof RateLimitError) return NextResponse.json({ error: error.message }, { status: 429 });
    throw error;
  }
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: '資料格式不正確。' }, { status: 400 }); }
  const validated = validateCourseSubmission((body ?? {}) as Record<string, unknown>);
  if (!validated.ok) return NextResponse.json({ error: validated.error }, { status: 400 });

  await ensureDatabase();
  const db = getD1();
  const value = validated.value;
  const department = await db.prepare(`SELECT id, official_source_url FROM academic_departments
    WHERE university_id = ? AND name = ? LIMIT 1`).bind(value.universityId, value.department)
    .first<{ id: string; official_source_url: string }>();
  if (!department) return NextResponse.json({ error: '找不到指定系所。' }, { status: 404 });
  const duplicate = await db.prepare(`SELECT c.id FROM courses c
    JOIN course_instructors ci ON ci.course_id = c.id
    WHERE c.university_id = ? AND c.semester = ? AND c.name = ? AND ci.instructor_name = ? LIMIT 1`)
    .bind(value.universityId, value.semester, value.name, value.instructorName).first<{ id: string }>();
  if (duplicate) return NextResponse.json({ error: '這門課與授課教師已經存在。' }, { status: 409 });

  const suffix = crypto.randomUUID();
  const courseId = `user-course-${suffix}`;
  const sourceUrl = value.officialSourceUrl || department.official_source_url;
  const now = new Date().toISOString();
  await db.batch([
    db.prepare(`INSERT INTO courses (
      id, university_id, term, first_term, last_term, offered_terms, semester, course_code,
      name, department, official_source_url, department_source_url, source_type,
      submitted_by_user_id, created_at, updated_at
    ) VALUES (?, ?, ?, '', '', '', ?, ?, ?, ?, ?, ?, 'user', ?, ?, ?)`)
      .bind(courseId, value.universityId, `user-${value.semester}-${suffix}`, value.semester,
        `USER-${suffix}`, value.name, value.department, sourceUrl, department.official_source_url,
        user.id, now, now),
    db.prepare(`INSERT INTO course_instructors
      (course_id, instructor_name, professor_id, official_source_url, created_at)
      VALUES (?, ?, NULL, ?, ?)`)
      .bind(courseId, value.instructorName, sourceUrl, now),
  ]);
  return NextResponse.json({ course: await getCourse(makeCourseCardId(courseId, value.instructorName)) }, { status: 201 });
}
