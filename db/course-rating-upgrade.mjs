const legacyScoreColumns = [
  'learning_score',
  'workload_score',
  'exam_difficulty_score',
  'grading_standard_score',
];

/**
 * Identify the teacher-specific 1–5 course-rating table created by migration 0024.
 * Checking both its columns and constraints prevents an already-0–100 table from
 * being multiplied a second time.
 *
 * @param {string[]} columns
 * @param {string | null | undefined} createSql
 */
export function isLegacyCourseRatingOneToFiveSchema(columns, createSql) {
  const existing = new Set(columns);
  if (!existing.has('instructor_name') || existing.has('attendance_frequency_score')) return false;
  if (!legacyScoreColumns.every((column) => existing.has(column))) return false;
  const normalizedSql = String(createSql ?? '').replace(/\s+/g, ' ');
  return legacyScoreColumns.every((column) => new RegExp(`${column}\\s+BETWEEN\\s+1\\s+AND\\s+5`, 'i').test(normalizedSql));
}

export const legacyCourseRatingUpgradeStatements = [
  'DROP INDEX IF EXISTS idx_course_ratings_course',
  'DROP INDEX IF EXISTS idx_course_ratings_user',
  'DROP INDEX IF EXISTS idx_course_ratings_user_course_instructor',
  'ALTER TABLE course_ratings RENAME TO course_ratings_legacy_1_to_5',
  `CREATE TABLE course_ratings (
    id TEXT PRIMARY KEY NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    instructor_name TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    learning_score INTEGER CHECK (
      learning_score IS NULL OR (typeof(learning_score) = 'integer' AND learning_score BETWEEN 0 AND 100)
    ),
    workload_score INTEGER NOT NULL CHECK (
      typeof(workload_score) = 'integer' AND workload_score BETWEEN 0 AND 100
    ),
    exam_difficulty_score INTEGER NOT NULL CHECK (
      typeof(exam_difficulty_score) = 'integer' AND exam_difficulty_score BETWEEN 0 AND 100
    ),
    grading_standard_score INTEGER CHECK (
      grading_standard_score IS NULL OR (typeof(grading_standard_score) = 'integer' AND grading_standard_score BETWEEN 0 AND 100)
    ),
    attendance_frequency_score INTEGER CHECK (
      attendance_frequency_score IS NULL OR (
        typeof(attendance_frequency_score) = 'integer' AND attendance_frequency_score BETWEEN 0 AND 100
      )
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, course_id, instructor_name)
  )`,
  `INSERT INTO course_ratings (
    id, course_id, instructor_name, user_id, learning_score, workload_score,
    exam_difficulty_score, grading_standard_score, attendance_frequency_score,
    created_at, updated_at
  )
  SELECT id, course_id, instructor_name, user_id,
    learning_score * 20,
    workload_score * 20,
    exam_difficulty_score * 20,
    grading_standard_score * 20,
    NULL,
    created_at, updated_at
  FROM course_ratings_legacy_1_to_5`,
  'CREATE INDEX idx_course_ratings_course ON course_ratings(course_id, instructor_name)',
  'CREATE INDEX idx_course_ratings_user ON course_ratings(user_id)',
  `CREATE UNIQUE INDEX idx_course_ratings_user_course_instructor
    ON course_ratings(user_id, course_id, instructor_name)`,
];
