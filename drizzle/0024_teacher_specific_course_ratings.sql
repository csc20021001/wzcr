ALTER TABLE courses ADD COLUMN semester TEXT NOT NULL DEFAULT '';
--> statement-breakpoint
ALTER TABLE courses ADD COLUMN source_type TEXT NOT NULL DEFAULT 'official';
--> statement-breakpoint
ALTER TABLE courses ADD COLUMN submitted_by_user_id TEXT;
--> statement-breakpoint
UPDATE courses SET semester = CASE
  WHEN term LIKE '%-1' THEN '1'
  WHEN term LIKE '%-2' THEN '2'
  ELSE ''
END;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_courses_university_semester
ON courses(university_id, semester, department, name);
--> statement-breakpoint

DROP INDEX IF EXISTS idx_course_ratings_course;
--> statement-breakpoint
DROP INDEX IF EXISTS idx_course_ratings_user;
--> statement-breakpoint
DROP INDEX IF EXISTS idx_course_ratings_user_course;
--> statement-breakpoint
ALTER TABLE course_ratings RENAME TO course_ratings_legacy;
--> statement-breakpoint
CREATE TABLE course_ratings (
  id TEXT PRIMARY KEY NOT NULL,
  course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  instructor_name TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  learning_score INTEGER NOT NULL CHECK (learning_score BETWEEN 1 AND 5),
  workload_score INTEGER NOT NULL CHECK (workload_score BETWEEN 1 AND 5),
  exam_difficulty_score INTEGER NOT NULL CHECK (exam_difficulty_score BETWEEN 1 AND 5),
  grading_standard_score INTEGER NOT NULL CHECK (grading_standard_score BETWEEN 1 AND 5),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, course_id, instructor_name)
);
--> statement-breakpoint
INSERT INTO course_ratings (
  id, course_id, instructor_name, user_id, learning_score, workload_score,
  exam_difficulty_score, grading_standard_score, created_at, updated_at
)
SELECT legacy.id, legacy.course_id,
  COALESCE((SELECT MIN(ci.instructor_name) FROM course_instructors ci WHERE ci.course_id = legacy.course_id), '未指定教師'),
  legacy.user_id, legacy.learning_score, legacy.workload_score,
  legacy.exam_difficulty_score, legacy.grading_standard_score,
  legacy.created_at, legacy.updated_at
FROM course_ratings_legacy legacy;
--> statement-breakpoint
DROP TABLE course_ratings_legacy;
--> statement-breakpoint
CREATE INDEX idx_course_ratings_course ON course_ratings(course_id, instructor_name);
--> statement-breakpoint
CREATE INDEX idx_course_ratings_user ON course_ratings(user_id);
--> statement-breakpoint
CREATE UNIQUE INDEX idx_course_ratings_user_course_instructor
ON course_ratings(user_id, course_id, instructor_name);
--> statement-breakpoint
PRAGMA optimize;

