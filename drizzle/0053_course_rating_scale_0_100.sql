DROP INDEX IF EXISTS idx_course_ratings_course;
--> statement-breakpoint
DROP INDEX IF EXISTS idx_course_ratings_user;
--> statement-breakpoint
DROP INDEX IF EXISTS idx_course_ratings_user_course_instructor;
--> statement-breakpoint
ALTER TABLE course_ratings RENAME TO course_ratings_legacy_1_to_5;
--> statement-breakpoint
CREATE TABLE course_ratings (
  id TEXT PRIMARY KEY NOT NULL,
  course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  instructor_name TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workload_score INTEGER NOT NULL CHECK (
    typeof(workload_score) = 'integer' AND workload_score BETWEEN 0 AND 100
  ),
  exam_difficulty_score INTEGER NOT NULL CHECK (
    typeof(exam_difficulty_score) = 'integer' AND exam_difficulty_score BETWEEN 0 AND 100
  ),
  attendance_frequency_score INTEGER CHECK (
    attendance_frequency_score IS NULL OR (
      typeof(attendance_frequency_score) = 'integer' AND attendance_frequency_score BETWEEN 0 AND 100
    )
  ),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, course_id, instructor_name)
);
--> statement-breakpoint
INSERT INTO course_ratings (
  id, course_id, instructor_name, user_id, workload_score,
  exam_difficulty_score, attendance_frequency_score, created_at, updated_at
)
SELECT id, course_id, instructor_name, user_id,
  workload_score * 20,
  exam_difficulty_score * 20,
  NULL,
  created_at, updated_at
FROM course_ratings_legacy_1_to_5;
--> statement-breakpoint
CREATE INDEX idx_course_ratings_course ON course_ratings(course_id, instructor_name);
--> statement-breakpoint
CREATE INDEX idx_course_ratings_user ON course_ratings(user_id);
--> statement-breakpoint
CREATE UNIQUE INDEX idx_course_ratings_user_course_instructor
ON course_ratings(user_id, course_id, instructor_name);
--> statement-breakpoint
INSERT INTO app_runtime_state (key, value, updated_at)
VALUES ('schema_version', '2026-08-29-course-rating-100-v1', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
--> statement-breakpoint
PRAGMA optimize;
