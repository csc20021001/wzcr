import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const report = JSON.parse(readFileSync(new URL('../db/course-import-report.generated.json', import.meta.url), 'utf8'));

test('NIU production migration loads teacher-specific cards from official history', () => {
  const database = new DatabaseSync(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE professors (id TEXT PRIMARY KEY NOT NULL, university_id TEXT NOT NULL, name TEXT NOT NULL);
    CREATE TABLE courses (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id),
      term TEXT NOT NULL,
      first_term TEXT NOT NULL DEFAULT '',
      last_term TEXT NOT NULL DEFAULT '',
      offered_terms TEXT NOT NULL DEFAULT '',
      course_code TEXT NOT NULL,
      name TEXT NOT NULL,
      department TEXT NOT NULL,
      official_source_url TEXT NOT NULL,
      department_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (university_id, term, course_code)
    );
    CREATE TABLE course_instructors (
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      professor_id TEXT REFERENCES professors(id),
      official_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      PRIMARY KEY (course_id, instructor_name)
    );
    CREATE TABLE course_ratings (id TEXT PRIMARY KEY NOT NULL, course_id TEXT NOT NULL REFERENCES courses(id));
    CREATE TABLE app_runtime_state (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    INSERT INTO universities (id) VALUES ('niu');
  `);

  for (const file of report.niuMigrationFiles) {
    database.exec(readFileSync(new URL(`../drizzle/${file}`, import.meta.url), 'utf8'));
  }

  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM courses WHERE university_id = 'niu'").get().count, 4401);
  assert.equal(database.prepare('SELECT COUNT(*) AS count FROM course_instructors').get().count, 4401);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM courses WHERE name LIKE '%專題研究%'").get().count, 0);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM course_instructors WHERE instructor_name LIKE '%教師%' OR instructor_name LIKE '%待聘%'").get().count, 0);
  assert.equal(database.prepare("SELECT value FROM app_runtime_state WHERE key = 'schema_version'").get().value, '2026-08-29-niu-courses-v1');

  const rows = database.prepare(`SELECT c.term, c.first_term, c.last_term, c.official_source_url,
    c.department_source_url, ci.official_source_url AS instructor_source_url
    FROM courses c JOIN course_instructors ci ON ci.course_id = c.id`).all();
  for (const row of rows) {
    assert.match(row.term, /^1(?:0[6-9]|1[0-5])-[12]$/);
    assert.ok(row.first_term >= '106-1');
    assert.ok(row.last_term <= '115-1');
    for (const url of [row.official_source_url, row.department_source_url, row.instructor_source_url]) {
      const host = new URL(url).hostname;
      assert.ok(host === 'niu.edu.tw' || host.endsWith('.niu.edu.tw'), url);
    }
  }
  database.close();
});
