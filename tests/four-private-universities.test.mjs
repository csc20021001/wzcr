import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const report = JSON.parse(readFileSync(new URL('../db/four-school-course-report.generated.json', import.meta.url), 'utf8'));
const importer = readFileSync(new URL('../scripts/import-four-private-universities.py', import.meta.url), 'utf8');
const directory = readFileSync(new URL('../app/courses/course-directory.tsx', import.meta.url), 'utf8');

test('four private universities use auditable official course coverage', () => {
  assert.equal(report.sourcePolicy, 'official university domains only');
  assert.deepEqual(Object.keys(report.schools).sort(), ['cycu', 'fcu', 'tku', 'yzu']);
  assert.equal(report.totalCourseRows, 18416);
  assert.equal(report.totalTeacherCards, 38950);
  assert.equal(report.schools.cycu.coverage, '1061-1151');
  assert.equal(report.schools.fcu.coverage, '1071-1151');
  assert.equal(report.schools.yzu.successfulOfficialUnits, report.schools.yzu.requestedOfficialUnits);
  assert.ok(report.schools.tku.officialPages > 150);
  assert.equal(report.migrationFiles.length, 25);
  for (const file of report.migrationFiles) {
    assert.ok(statSync(new URL(`../drizzle/${file}`, import.meta.url)).size < 1_000_000, `${file} is too large`);
  }
  assert.match(importer, /active_teachers=active/);
  assert.match(importer, /"專題研究" in course_name/);
  assert.match(importer, /Rejected non-official URL/);
});

test('generated migrations load every school and split each instructor into a rating card', () => {
  const db = new DatabaseSync(':memory:');
  db.exec('PRAGMA foreign_keys = ON');
  db.exec(`
    CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE academic_departments (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
      college TEXT NOT NULL,
      name TEXT NOT NULL,
      unit_type TEXT NOT NULL,
      official_source_url TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (university_id, name)
    );
    CREATE TABLE courses (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
      term TEXT NOT NULL,
      first_term TEXT NOT NULL DEFAULT '',
      last_term TEXT NOT NULL DEFAULT '',
      offered_terms TEXT NOT NULL DEFAULT '',
      semester TEXT NOT NULL DEFAULT '',
      course_code TEXT NOT NULL,
      name TEXT NOT NULL,
      department TEXT NOT NULL,
      official_source_url TEXT NOT NULL,
      department_source_url TEXT NOT NULL DEFAULT '',
      source_type TEXT NOT NULL DEFAULT 'official',
      submitted_by_user_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (university_id, term, course_code)
    );
    CREATE TABLE course_instructors (
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      professor_id TEXT,
      official_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      PRIMARY KEY (course_id, instructor_name)
    );
    CREATE TABLE course_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE
    );
  `);
  const insertSchool = db.prepare('INSERT INTO universities (id) VALUES (?)');
  for (const school of ['cycu', 'tku', 'yzu', 'fcu']) insertSchool.run(school);
  db.exec('BEGIN');
  try {
    for (const file of report.migrationFiles) {
      db.exec(readFileSync(new URL(`../drizzle/${file}`, import.meta.url), 'utf8'));
    }
    db.exec('COMMIT');
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }

  for (const [school, expected] of Object.entries(report.schools)) {
    const courseCount = db.prepare('SELECT COUNT(*) AS count FROM courses WHERE university_id = ?').get(school).count;
    const cardCount = db.prepare(`SELECT COUNT(*) AS count FROM course_instructors ci
      JOIN courses c ON c.id = ci.course_id WHERE c.university_id = ?`).get(school).count;
    assert.equal(courseCount, expected.courseRows, school);
    assert.equal(cardCount, expected.teacherCards, school);
  }
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM courses WHERE name LIKE '%專題研究%'").get().count, 0);
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM courses WHERE semester NOT IN ('1', '2')").get().count, 0);
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM courses WHERE term NOT IN ('official-1', 'official-2')").get().count, 0);
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM courses WHERE source_type != 'official'").get().count, 0);

  const suffixes = { cycu: 'cycu.edu.tw', tku: 'tku.edu.tw', yzu: 'yzu.edu.tw', fcu: 'fcu.edu.tw' };
  const courseIndexes = new Set(Object.values(report.schools).map((school) => school.officialIndex));
  const urls = db.prepare(`SELECT c.university_id, c.official_source_url AS course_url,
    c.department_source_url AS department_url, ci.official_source_url AS instructor_url,
    ci.instructor_name FROM courses c JOIN course_instructors ci ON ci.course_id = c.id`).all();
  for (const row of urls) {
    assert.doesNotMatch(row.instructor_name, /助\s*教|待\s*聘|指導教授|授課教師/);
    for (const value of [row.course_url, row.department_url, row.instructor_url]) {
      const host = new URL(value).hostname;
      const suffix = suffixes[row.university_id];
      assert.ok(host === suffix || host.endsWith(`.${suffix}`), value);
    }
    assert.ok(!courseIndexes.has(row.department_url), row.department_url);
    assert.doesNotMatch(new URL(row.department_url).pathname, /\.(?:docx?|gif|jpe?g|pdf|png|pptx?|svg|webp|xlsx?|zip)$/i);
  }
  for (const school of Object.keys(report.schools)) {
    const distinct = db.prepare(`SELECT COUNT(DISTINCT department_source_url) AS count
      FROM courses WHERE university_id = ?`).get(school).count;
    assert.ok(distinct > 1, `${school} should resolve department links beyond one generic course portal`);
  }
  db.close();
});

test('course UI shows only semester labels and supports signed-in course submissions', () => {
  assert.match(directory, /新增課程/);
  assert.match(directory, /上學期/);
  assert.match(directory, /下學期/);
  assert.match(directory, /\/api\/courses/);
  assert.doesNotMatch(directory, /course\.courseCode|course\.firstTerm|course\.lastTerm|course\.offeredTerms/);
  assert.doesNotMatch(directory, /學期數|課程代碼|學年度/);
});
