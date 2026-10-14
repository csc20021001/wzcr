CREATE TABLE courses (
  id TEXT PRIMARY KEY NOT NULL,
  university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  term TEXT NOT NULL,
  course_code TEXT NOT NULL,
  name TEXT NOT NULL,
  department TEXT NOT NULL,
  official_source_url TEXT NOT NULL,
  department_source_url TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (university_id, term, course_code)
);

CREATE INDEX idx_courses_university_term ON courses(university_id, term, department, name);
CREATE INDEX idx_courses_name ON courses(name);
CREATE INDEX idx_courses_department ON courses(department);

CREATE TABLE course_instructors (
  course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  instructor_name TEXT NOT NULL,
  professor_id TEXT REFERENCES professors(id) ON DELETE SET NULL,
  official_source_url TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY (course_id, instructor_name)
);

CREATE INDEX idx_course_instructors_name ON course_instructors(instructor_name);
CREATE INDEX idx_course_instructors_professor ON course_instructors(professor_id);

CREATE TABLE course_ratings (
  id TEXT PRIMARY KEY NOT NULL,
  course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  learning_score INTEGER NOT NULL CHECK (learning_score BETWEEN 1 AND 5),
  workload_score INTEGER NOT NULL CHECK (workload_score BETWEEN 1 AND 5),
  exam_difficulty_score INTEGER NOT NULL CHECK (exam_difficulty_score BETWEEN 1 AND 5),
  grading_standard_score INTEGER NOT NULL CHECK (grading_standard_score BETWEEN 1 AND 5),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, course_id)
);

CREATE INDEX idx_course_ratings_course ON course_ratings(course_id);
CREATE INDEX idx_course_ratings_user ON course_ratings(user_id);
