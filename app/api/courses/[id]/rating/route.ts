import { NextResponse } from 'next/server';
import { getSessionUser, isSameOriginRequest } from '@/app/auth/server';
import { ensureDatabase, getD1 } from '@/db';
import { getCourse, parseCourseCardId } from '@/db/courses';
import { enforceUserRateLimit, RateLimitError } from '@/db/rate-limit';
import { validateCourseRating } from '../../validation.mjs';

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  if (!isSameOriginRequest(request)) return NextResponse.json({ error: '不允許跨站評分。' }, { status: 403 });
  const user = await getSessionUser(request);
  if (!user) return NextResponse.json({ error: '請先使用 Google 登入。' }, { status: 401 });
  const { id } = await context.params;
  const identity = parseCourseCardId(id);
  if (!identity) return NextResponse.json({ error: '課程識別格式不正確。' }, { status: 400 });
  try {
    await enforceUserRateLimit(user.id, 'course-rating', 25, 60);
  } catch (error) {
    if (error instanceof RateLimitError) return NextResponse.json({ error: error.message }, { status: 429 });
    throw error;
  }
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: '資料格式不正確。' }, { status: 400 }); }
  const validated = validateCourseRating((body ?? {}) as Record<string, unknown>);
  if (!validated.ok) return NextResponse.json({ error: validated.error }, { status: 400 });

  await ensureDatabase();
  const db = getD1();
  if (!await db.prepare(`SELECT c.id FROM courses c JOIN course_instructors ci ON ci.course_id = c.id
      WHERE c.id = ? AND ci.instructor_name = ? LIMIT 1`)
    .bind(identity.courseId, identity.instructorName).first()) {
    return NextResponse.json({ error: '找不到課程資料。' }, { status: 404 });
  }
  const now = new Date().toISOString();
  const { learningScore, workloadScore, examDifficultyScore, gradingStandardScore, attendanceFrequencyScore } = validated.value;
  await db.prepare(`INSERT INTO course_ratings (
      id, course_id, instructor_name, user_id, learning_score, workload_score,
      exam_difficulty_score, grading_standard_score, attendance_frequency_score, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id, course_id, instructor_name) DO UPDATE SET
      learning_score = excluded.learning_score,
      workload_score = excluded.workload_score,
      exam_difficulty_score = excluded.exam_difficulty_score,
      grading_standard_score = excluded.grading_standard_score,
      attendance_frequency_score = excluded.attendance_frequency_score,
      updated_at = excluded.updated_at`)
    .bind(
      crypto.randomUUID(), identity.courseId, identity.instructorName, user.id, learningScore, workloadScore,
      examDifficultyScore, gradingStandardScore, attendanceFrequencyScore, now, now,
    ).run();
  return NextResponse.json({ course: await getCourse(id) });
}
