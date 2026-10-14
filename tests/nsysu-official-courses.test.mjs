import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const report = JSON.parse(readFileSync(
  new URL('../db/nsysu-course-report.generated.json', import.meta.url),
  'utf8',
));
const aggregate = JSON.parse(readFileSync(
  new URL('../db/course-import-report.generated.json', import.meta.url),
  'utf8',
));
const facultyCandidates = JSON.parse(readFileSync(
  new URL('../db/professor-candidates.generated.json', import.meta.url),
  'utf8',
));
const importer = readFileSync(
  new URL('../scripts/import-nsysu-official-course-history.py', import.meta.url),
  'utf8',
);
const baseImporter = readFileSync(
  new URL('../scripts/import-official-course-history.py', import.meta.url),
  'utf8',
);
const expectedTerms = [
  '106-1', '106-2', '107-1', '107-2', '108-1', '108-2', '109-1', '109-2',
  '110-1', '110-2', '111-1', '111-2', '112-1', '112-2', '113-1', '113-2',
  '114-1', '114-2', '115-1',
];
const migrationSql = report.migrationFiles.map((name) => readFileSync(
  new URL(`../drizzle/${name}`, import.meta.url),
  'utf8',
));

function createDatabase() {
  const database = new DatabaseSync(':memory:');
  database.exec('PRAGMA foreign_keys = ON');
  database.exec(`
    CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
    INSERT INTO universities (id) VALUES ('nsysu'), ('ntust');
    CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE professors (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL,
      name TEXT NOT NULL
    );
    CREATE TABLE courses (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
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
      semester TEXT NOT NULL DEFAULT '',
      source_type TEXT NOT NULL DEFAULT 'official',
      submitted_by_user_id TEXT
    );
    CREATE TABLE course_instructors (
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      professor_id TEXT REFERENCES professors(id) ON DELETE SET NULL,
      official_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      PRIMARY KEY (course_id, instructor_name)
    );
    CREATE TABLE course_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      user_id TEXT NOT NULL
    );
    CREATE TABLE app_runtime_state (
      key TEXT PRIMARY KEY NOT NULL,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  `);
  return database;
}

function applyMigrations(database) {
  for (const sql of migrationSql) {
    for (const statement of sql.split('--> statement-breakpoint').map((part) => part.trim()).filter(Boolean)) {
      database.exec(statement);
    }
  }
}

function assertOfficialNsysuUrl(value) {
  const url = new URL(value);
  assert.equal(url.protocol, 'https:');
  assert.ok(
    url.hostname === 'nsysu.edu.tw' || url.hostname.endsWith('.nsysu.edu.tw'),
    `${value} is not an official NSYSU URL`,
  );
}

function insertCourse(database, { id, universityId, name, sourceType = 'official' }) {
  database.prepare(`INSERT INTO courses (
    id, university_id, term, first_term, last_term, offered_terms, course_code, name,
    department, official_source_url, department_source_url, created_at, updated_at,
    semester, source_type
  ) VALUES (?, ?, '115-1', '115-1', '115-1', '115-1', ?, ?, '測試系',
    'https://www.nsysu.edu.tw/', 'https://www.nsysu.edu.tw/', 'now', 'now', '1', ?)`)
    .run(id, universityId, id, name, sourceType);
  database.prepare(`INSERT INTO course_instructors (
    course_id, instructor_name, professor_id, official_source_url, created_at
  ) VALUES (?, '測試教師', NULL, 'https://www.nsysu.edu.tw/', 'now')`).run(id);
}

test('NSYSU report proves complete official coverage for 106-1 through 115-1', () => {
  assert.equal(report.status, 'imported');
  assert.equal(report.policy.officialUniversityDomainsOnly, true);
  assert.equal(report.policy.captchaBypassed, false);
  assert.equal(report.policy.requiresCurrentOfficialInstructorEvidence, true);
  assert.equal(report.policy.inactiveOrUnverifiedInstructorsPublished, false);
  assert.equal(report.policy.specialResearchCoursesExcluded, true);
  assert.equal(report.policy.failClosedResponseValidation, true);
  assert.equal(report.policy.completeStaticUnitCatalogPerTerm, true);
  assert.ok(report.unitCatalogCount >= 300);
  assert.deepEqual(report.availableTerms, expectedTerms);
  assert.deepEqual(report.missingTerms, []);
  assert.deepEqual(report.failedDepartmentQueries, []);
  assert.equal(report.terms.length, expectedTerms.length);
  assert.equal(report.departmentQueries, report.unitCatalogCount * expectedTerms.length);
  assert.equal(report.successfulDepartmentQueries, report.departmentQueries);
  assert.ok(report.parsedOfferings > 40_000);
  assert.ok(report.verifiedCourses > 6_000);
  assert.ok(report.publishedCourseInstructorCards > 10_000);
  assert.ok(report.publishedCourseInstructorCards >= report.verifiedCourses);
  assert.ok(report.activeInstructorCount > 500);
  assert.ok(report.excludedSpecialResearch > 0);

  for (const [index, term] of expectedTerms.entries()) {
    const termReport = report.terms[index];
    assert.equal(termReport.term, term);
    assert.equal(termReport.departmentQueries, report.unitCatalogCount);
    assert.equal(termReport.successfulDepartmentQueries, report.unitCatalogCount);
    assert.deepEqual(termReport.failedDepartmentQueries, []);
    assert.ok(termReport.parsedOfferings >= report.minimumOfferingsPerTerm, term);
  }
  assert.ok(report.migrationFiles.length > 1);
  for (const name of report.migrationFiles) {
    assert.ok(statSync(new URL(`../drizzle/${name}`, import.meta.url)).size < 900 * 1024, name);
  }

  const school = aggregate.schools.find((row) => row.universityId === 'nsysu');
  assert.equal(school.status, 'imported');
  assert.deepEqual(school.availableTerms, expectedTerms);
  assert.deepEqual(school.missingTerms, []);
  assert.equal(school.verifiedCourses, report.verifiedCourses);
  assert.equal(school.activeFacultyCount, report.activeFacultyPageCount);
  assert.equal(school.activeInstructorCount, report.activeInstructorCount);
  assert.deepEqual(aggregate.nsysuMigrationFiles, report.migrationFiles);
  assert.equal(
    aggregate.courseCount,
    aggregate.baseImporterCourseCount + report.verifiedCourses,
  );
});

test('NSYSU migrations load one official card per course and current instructor', () => {
  const database = createDatabase();
  applyMigrations(database);
  const courseCount = database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE university_id = 'nsysu' AND source_type = 'official'`).get().count;
  const cardCount = database.prepare(`SELECT COUNT(*) AS count FROM course_instructors ci
    JOIN courses c ON c.id = ci.course_id
    WHERE c.university_id = 'nsysu' AND c.source_type = 'official'`).get().count;
  assert.equal(courseCount, report.verifiedCourses);
  assert.equal(cardCount, report.publishedCourseInstructorCards);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses c
    WHERE c.university_id = 'nsysu' AND NOT EXISTS (
      SELECT 1 FROM course_instructors ci WHERE ci.course_id = c.id
    )`).get().count, 0);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE university_id = 'nsysu' AND name LIKE '%專題研究%'`).get().count, 0);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM (
    SELECT course_id, instructor_name, COUNT(*) AS copies
    FROM course_instructors GROUP BY course_id, instructor_name HAVING copies > 1
  )`).get().count, 0);

  for (const term of expectedTerms) {
    const count = database.prepare(`SELECT COUNT(*) AS count FROM courses
      WHERE university_id = 'nsysu'
      AND instr(',' || offered_terms || ',', ',' || ? || ',') > 0`).get(term).count;
    assert.ok(count > 100, `${term} has too few published courses`);
  }
  for (const row of database.prepare(`SELECT official_source_url, department_source_url
    FROM courses WHERE university_id = 'nsysu'`).all()) {
    assertOfficialNsysuUrl(row.official_source_url);
    assertOfficialNsysuUrl(row.department_source_url);
  }
  const facultyEvidence = new Set(facultyCandidates
    .filter((row) => row.universityId === 'nsysu')
    .map((row) => `${row.name}\0${row.sourceUrl}`));
  for (const row of database.prepare(`SELECT ci.instructor_name, ci.official_source_url
    FROM course_instructors ci JOIN courses c ON c.id = ci.course_id
    WHERE c.university_id = 'nsysu'`).all()) {
    assertOfficialNsysuUrl(row.official_source_url);
    if (!facultyEvidence.has(`${row.instructor_name}\0${row.official_source_url}`)) {
      const evidenceUrl = new URL(row.official_source_url);
      assert.equal(evidenceUrl.hostname, 'selcrs.nsysu.edu.tw');
      assert.equal(evidenceUrl.searchParams.get('QM_SYEAR'), '115');
      assert.equal(evidenceUrl.searchParams.get('QM_SEM'), '1');
      assert.equal(evidenceUrl.searchParams.get('QM_ACTION'), '2');
    }
  }
  database.close();
});

test('NSYSU refresh removes stale official cards without discarding normal ratings', () => {
  const database = createDatabase();
  applyMigrations(database);
  database.exec("INSERT INTO users (id) VALUES ('user-1')");
  const current = database.prepare(`SELECT c.id, ci.instructor_name
    FROM courses c JOIN course_instructors ci ON ci.course_id = c.id
    WHERE c.university_id = 'nsysu' LIMIT 1`).get();
  database.prepare(`INSERT INTO course_instructors (
    course_id, instructor_name, professor_id, official_source_url, created_at
  ) VALUES (?, '已離校教師', NULL, 'https://www.nsysu.edu.tw/', 'before')`).run(current.id);
  database.prepare(`INSERT INTO course_ratings (id, course_id, instructor_name, user_id)
    VALUES ('normal-rating', ?, '已離校教師', 'user-1')`).run(current.id);

  insertCourse(database, { id: 'stale-official', universityId: 'nsysu', name: '舊官方課程' });
  insertCourse(database, { id: 'user-course', universityId: 'nsysu', name: '使用者課程', sourceType: 'user' });
  insertCourse(database, { id: 'outside-course', universityId: 'ntust', name: '校外官方課程' });
  insertCourse(database, { id: 'special-course', universityId: 'nsysu', name: '專題研究' });
  database.exec(`INSERT INTO course_ratings VALUES
    ('special-rating', 'special-course', '測試教師', 'user-1')`);

  applyMigrations(database);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM course_ratings
    WHERE id = 'normal-rating'`).get().count, 1);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE id = ?`).get(current.id).count, 1);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM course_instructors
    WHERE course_id = ? AND instructor_name = '已離校教師'`).get(current.id).count, 0);
  assert.ok(database.prepare(`SELECT COUNT(*) AS count FROM course_instructors
    WHERE course_id = ?`).get(current.id).count > 0);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE id = 'stale-official'`).get().count, 0);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE id = 'user-course'`).get().count, 1);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE id = 'outside-course'`).get().count, 1);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM courses
    WHERE id = 'special-course'`).get().count, 0);
  assert.equal(database.prepare(`SELECT COUNT(*) AS count FROM course_ratings
    WHERE id = 'special-rating'`).get().count, 0);
  database.close();
});

test('NSYSU importer fails closed and keeps committed migration batches immutable', () => {
  assert.match(importer, /validate_department_catalog/);
  assert.match(importer, /validate_course_report_payload/);
  assert.match(importer, /successfulDepartmentQueries/);
  assert.match(importer, /MIN_OFFERINGS_PER_TERM\s*=\s*1_000/);
  assert.match(importer, /payload\.decode\("utf-8"\)/);
  assert.match(importer, /official_url\(response\.geturl\(\)\)/);
  assert.doesNotMatch(importer, /validcode|tesseract|easyocr|pytesseract/i);
  const guard = importer.indexOf('if committed_batch:');
  const unlink = importer.indexOf('path.unlink()', guard);
  assert.ok(guard >= 0 && unlink > guard);
  assert.match(baseImporter, /def overlay_nsysu_supplement/);
  assert.match(baseImporter, /failClosedResponseValidation/);
});
