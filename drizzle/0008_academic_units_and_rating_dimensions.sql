CREATE TABLE IF NOT EXISTS academic_departments (
  id TEXT PRIMARY KEY NOT NULL,
  university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  college TEXT NOT NULL,
  name TEXT NOT NULL,
  unit_type TEXT NOT NULL CHECK (unit_type IN ('department', 'institute', 'program', 'academic-unit')),
  official_source_url TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (university_id, name)
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_departments_identity
  ON academic_departments(university_id, name);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_academic_departments_university_college
  ON academic_departments(university_id, college, name);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_academic_departments_name
  ON academic_departments(name);
--> statement-breakpoint
ALTER TABLE professor_ratings ADD COLUMN attitude_score INTEGER NOT NULL DEFAULT 3
  CHECK (attitude_score BETWEEN 1 AND 5);
--> statement-breakpoint
ALTER TABLE professor_ratings ADD COLUMN workload_score INTEGER NOT NULL DEFAULT 3
  CHECK (workload_score BETWEEN 1 AND 5);
--> statement-breakpoint
ALTER TABLE professor_ratings ADD COLUMN exam_difficulty_score INTEGER NOT NULL DEFAULT 3
  CHECK (exam_difficulty_score BETWEEN 1 AND 5);
--> statement-breakpoint
ALTER TABLE professor_ratings ADD COLUMN grading_standard_score INTEGER NOT NULL DEFAULT 3
  CHECK (grading_standard_score BETWEEN 1 AND 5);
--> statement-breakpoint
PRAGMA optimize;
