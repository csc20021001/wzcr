import { getD1 } from './index';

export type CourseInstructorView = { name: string; officialSourceUrl: string };

export type CourseView = {
  id: string;
  courseId: string;
  universityId: string;
  semester: '1' | '2';
  courseCode: string;
  name: string;
  department: string;
  officialSourceUrl: string;
  departmentSourceUrl: string;
  sourceType: 'official' | 'user';
  instructors: CourseInstructorView[];
  averageRating: number | null;
  averageLearning: number | null;
  averageWorkload: number | null;
  averageExamDifficulty: number | null;
  averageGradingStandard: number | null;
  averageAttendanceFrequency: number | null;
  ratingCount: number;
};

type CourseRow = {
  id: string;
  university_id: string;
  semester: string;
  course_code: string;
  name: string;
  department: string;
  official_source_url: string;
  department_source_url: string;
  source_type: string;
  instructor_name: string;
  instructor_source_url: string;
  average_rating: number | null;
  average_learning: number | null;
  average_workload: number | null;
  average_exam_difficulty: number | null;
  average_grading_standard: number | null;
  average_attendance_frequency: number | null;
  rating_count: number;
};

const numericOrNull = (value: number | null) => value === null ? null : Number(value);

export function makeCourseCardId(courseId: string, instructorName: string) {
  return `${courseId}~${encodeURIComponent(instructorName)}`;
}

export function parseCourseCardId(value: string) {
  const separator = value.lastIndexOf('~');
  if (separator <= 0) return null;
  try {
    const courseId = value.slice(0, separator);
    const instructorName = decodeURIComponent(value.slice(separator + 1));
    if (!/^[a-z0-9-]{2,100}$/i.test(courseId) || instructorName.length < 1 || instructorName.length > 80) return null;
    return { courseId, instructorName };
  } catch {
    return null;
  }
}

function mapCourse(row: CourseRow): CourseView {
  const semester = row.semester === '2' ? '2' : '1';
  return {
    id: makeCourseCardId(row.id, row.instructor_name),
    courseId: row.id,
    universityId: row.university_id,
    semester,
    courseCode: row.course_code,
    name: row.name,
    department: row.department,
    officialSourceUrl: row.official_source_url,
    departmentSourceUrl: row.department_source_url,
    sourceType: row.source_type === 'user' ? 'user' : 'official',
    instructors: [{ name: row.instructor_name, officialSourceUrl: row.instructor_source_url }],
    averageRating: numericOrNull(row.average_rating),
    averageLearning: numericOrNull(row.average_learning),
    averageWorkload: numericOrNull(row.average_workload),
    averageExamDifficulty: numericOrNull(row.average_exam_difficulty),
    averageGradingStandard: numericOrNull(row.average_grading_standard),
    averageAttendanceFrequency: numericOrNull(row.average_attendance_frequency),
    ratingCount: Number(row.rating_count),
  };
}

const selectWithRatings = `
  SELECT c.id, c.university_id, c.semester, c.course_code, c.name, c.department,
    c.official_source_url, c.department_source_url, c.source_type,
    ci.instructor_name, ci.official_source_url AS instructor_source_url,
    ROUND(AVG((
      cr.workload_score + cr.exam_difficulty_score +
      CASE WHEN cr.learning_score IS NULL THEN 0 ELSE cr.learning_score END +
      CASE WHEN cr.grading_standard_score IS NULL THEN 0 ELSE cr.grading_standard_score END +
      CASE WHEN cr.attendance_frequency_score IS NULL THEN 0 ELSE cr.attendance_frequency_score END
    ) / (
      2.0 +
      CASE WHEN cr.learning_score IS NULL THEN 0 ELSE 1 END +
      CASE WHEN cr.grading_standard_score IS NULL THEN 0 ELSE 1 END +
      CASE WHEN cr.attendance_frequency_score IS NULL THEN 0 ELSE 1 END
    )), 1) AS average_rating,
    ROUND(AVG(cr.learning_score), 1) AS average_learning,
    ROUND(AVG(cr.workload_score), 1) AS average_workload,
    ROUND(AVG(cr.exam_difficulty_score), 1) AS average_exam_difficulty,
    ROUND(AVG(cr.grading_standard_score), 1) AS average_grading_standard,
    ROUND(AVG(cr.attendance_frequency_score), 1) AS average_attendance_frequency,
    COUNT(cr.id) AS rating_count
  FROM courses c
  JOIN course_instructors ci ON ci.course_id = c.id
  LEFT JOIN course_ratings cr ON cr.course_id = c.id AND cr.instructor_name = ci.instructor_name
`;

export async function listCourses(filters: {
  universityId?: string;
  department?: string;
  search?: string;
  semester?: string;
  limit?: number;
  offset?: number;
}) {
  const conditions: string[] = ["c.name NOT LIKE '%專題研究%'"];
  const values: Array<string | number> = [];
  if (filters.universityId) {
    conditions.push('c.university_id = ?');
    values.push(filters.universityId);
  }
  if (filters.department) {
    conditions.push('c.department LIKE ?');
    values.push(`%${filters.department}%`);
  }
  if (filters.search) {
    conditions.push('(c.name LIKE ? OR c.department LIKE ? OR ci.instructor_name LIKE ?)');
    const needle = `%${filters.search}%`;
    values.push(needle, needle, needle);
  }
  if (filters.semester) {
    conditions.push('c.semester = ?');
    values.push(filters.semester);
  }
  const where = `WHERE ${conditions.join(' AND ')}`;
  const limit = Math.min(60, Math.max(1, filters.limit ?? 36));
  const offset = Math.max(0, filters.offset ?? 0);
  const countRow = await getD1().prepare(`SELECT COUNT(*) AS total
    FROM courses c JOIN course_instructors ci ON ci.course_id = c.id ${where}`)
    .bind(...values).first<{ total: number }>();
  const result = await getD1().prepare(`${selectWithRatings}
    ${where}
    GROUP BY c.id, ci.instructor_name
    ORDER BY rating_count DESC, c.department, c.name, ci.instructor_name
    LIMIT ? OFFSET ?
  `).bind(...values, limit, offset).all<CourseRow>();
  const courses = result.results.map(mapCourse);
  const total = Number(countRow?.total ?? 0);
  return { courses, total, nextOffset: offset + courses.length < total ? offset + courses.length : null };
}

export async function getCourse(cardId: string) {
  const identity = parseCourseCardId(cardId);
  if (!identity) return null;
  const row = await getD1().prepare(`${selectWithRatings}
    WHERE c.id = ? AND ci.instructor_name = ? AND c.name NOT LIKE '%專題研究%'
    GROUP BY c.id, ci.instructor_name
  `).bind(identity.courseId, identity.instructorName).first<CourseRow>();
  return row ? mapCourse(row) : null;
}
