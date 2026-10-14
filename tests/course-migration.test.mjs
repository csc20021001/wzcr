import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const migration = (name) => readFileSync(new URL(`../drizzle/${name}`, import.meta.url), 'utf8')
  .split('--> statement-breakpoint')
  .map((statement) => statement.trim())
  .filter(Boolean);

test('official course history migration loads the generated snapshot into SQLite', () => {
  const report = JSON.parse(readFileSync(new URL('../db/course-import-report.generated.json', import.meta.url), 'utf8'));
  const db = new DatabaseSync(':memory:');
  db.exec('PRAGMA foreign_keys = ON');
  db.exec(`
    CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE professors (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id),
      name TEXT NOT NULL
    );
  `);
  const insertUniversity = db.prepare('INSERT INTO universities (id) VALUES (?)');
  for (const id of ['ntu', 'nthu', 'nycu', 'ncu', 'nchu', 'ccu', 'nsysu', 'ntust', 'ntut', 'niu']) {
    insertUniversity.run(id);
  }

  db.exec('BEGIN');
  try {
    for (const file of ['0013_courses_and_course_ratings.sql', '0014_course_history_terms.sql', ...report.courseMigrationFiles]) {
      for (const statement of migration(file)) db.exec(statement);
    }
    db.exec('COMMIT');
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }

  const courseCount = db.prepare('SELECT COUNT(*) AS count FROM courses').get().count;
  const instructorCount = db.prepare('SELECT COUNT(*) AS count FROM course_instructors').get().count;
  const schoolCount = db.prepare('SELECT COUNT(DISTINCT university_id) AS count FROM courses').get().count;
  const range = db.prepare('SELECT MIN(first_term) AS first, MAX(last_term) AS last FROM courses').get();
  const futureCount = db.prepare("SELECT COUNT(*) AS count FROM courses WHERE ',' || offered_terms || ',' LIKE '%,115-2,%'").get().count;
  const courses = db.prepare('SELECT university_id, term, official_source_url, department_source_url FROM courses').all();
  const instructors = db.prepare('SELECT c.university_id, ci.instructor_name, ci.official_source_url FROM course_instructors ci JOIN courses c ON c.id = ci.course_id').all();
  const suffixes = {
    ntu: 'ntu.edu.tw', nthu: 'nthu.edu.tw', nycu: 'nycu.edu.tw',
    ncu: 'ncu.edu.tw', nchu: 'nchu.edu.tw', ccu: 'ccu.edu.tw', nsysu: 'nsysu.edu.tw',
    ntust: 'ntust.edu.tw', ntut: 'ntut.edu.tw', niu: 'niu.edu.tw',
  };

  assert.equal(courseCount, report.baseSnapshotCourseCount);
  assert.ok(instructorCount > courseCount);
  assert.equal(schoolCount, 9);
  assert.equal(range.first, '106-1');
  assert.equal(range.last, '115-1');
  assert.equal(futureCount, 0);
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM courses WHERE university_id = 'niu'").get().count, 4401);
  assert.equal(db.prepare(`SELECT COUNT(*) AS count FROM (
    SELECT c.id FROM courses c JOIN course_instructors ci ON ci.course_id = c.id
    WHERE c.university_id = 'niu' GROUP BY c.id HAVING COUNT(*) != 1
  )`).get().count, 0);
  for (const course of courses) {
    assert.match(course.term, /^1(?:0[6-9]|1[0-5])-[12]$/);
    for (const url of [course.official_source_url, course.department_source_url]) {
      const host = new URL(url).hostname;
      const suffix = suffixes[course.university_id];
      assert.ok(host === suffix || host.endsWith(`.${suffix}`), url);
    }
    assert.notEqual(course.official_source_url, course.department_source_url, course.official_source_url);
    assert.doesNotMatch(new URL(course.department_source_url).pathname, /\.(?:docx?|gif|jpe?g|pdf|png|pptx?|svg|webp|xlsx?|zip)$/i);
  }
  assert.ok(instructors.some((row) => /^[\u3400-\u9fff]{2,8}$/.test(row.instructor_name)));
  for (const instructor of instructors) {
    assert.doesNotMatch(instructor.instructor_name, /各課程|授課教師|學系|學程/);
    const host = new URL(instructor.official_source_url).hostname;
    const suffix = suffixes[instructor.university_id];
    assert.ok(host === suffix || host.endsWith(`.${suffix}`), instructor.official_source_url);
  }
  db.close();
});
