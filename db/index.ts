import { env } from 'cloudflare:workers';
import { drizzle } from 'drizzle-orm/d1';
import * as schema from './schema';
import { universities } from '../app/data';
import { professorSeeds } from './professors-seeds.generated';
import { departmentSeeds } from './department-seeds';
import {
  isLegacyCourseRatingOneToFiveSchema,
  legacyCourseRatingUpgradeStatements,
} from './course-rating-upgrade.mjs';
const activeUniversityIds = new Set(universities.map((school) => school.id));

let databaseReady: Promise<void> | null = null;
const runtimeSchemaVersion = '2026-08-29-course-rating-five-dimensions-v1';

export function getD1() {
  if (!env.DB) throw new Error('Cloudflare D1 binding `DB` is unavailable.');
  return env.DB;
}

export function getDb() {
  return drizzle(getD1(), { schema });
}

async function isRuntimeSchemaReady() {
  try {
    const state = await getD1().prepare(`SELECT value,
      (SELECT COUNT(*) FROM universities) AS university_count,
      (SELECT COUNT(*) FROM academic_departments) AS department_count,
      (SELECT COUNT(*) FROM professors) AS professor_count,
      (SELECT COUNT(*) FROM courses) AS course_count
      FROM app_runtime_state WHERE key = 'schema_version'`).first<{
        value: string;
        university_count: number;
        department_count: number;
        professor_count: number;
        course_count: number;
      }>();
    return state?.value === runtimeSchemaVersion
      && Number(state.university_count) > 0
      && Number(state.department_count) > 0
      && Number(state.professor_count) > 0
      && Number(state.course_count) > 0;
  } catch {
    return false;
  }
}

async function ensureUniversityCreatedAt() {
  const db = getD1();
  const tableInfo = await db.prepare('PRAGMA table_info(universities)').all<{ name: string }>();
  if (tableInfo.results.length > 0 && !tableInfo.results.some((column) => column.name === 'created_at')) {
    await db.prepare('ALTER TABLE universities ADD COLUMN created_at TEXT').run();
  }
}

async function ensureProfessorOfficialSourceUrl() {
  const db = getD1();
  const tableInfo = await db.prepare('PRAGMA table_info(professors)').all<{ name: string }>();
  if (tableInfo.results.length > 0 && !tableInfo.results.some((column) => column.name === 'official_source_url')) {
    await db.prepare("ALTER TABLE professors ADD COLUMN official_source_url TEXT NOT NULL DEFAULT ''").run();
  }
}

async function ensureProfessorRatingDimensions() {
  const db = getD1();
  const tableInfo = await db.prepare('PRAGMA table_info(professor_ratings)').all<{ name: string }>();
  if (tableInfo.results.length === 0) return;
  const existing = new Set(tableInfo.results.map((column) => column.name));
  const additions = [
    ['attitude_score', 'ALTER TABLE professor_ratings ADD COLUMN attitude_score INTEGER NOT NULL DEFAULT 3 CHECK (attitude_score BETWEEN 1 AND 5)'],
    ['learning_score', 'ALTER TABLE professor_ratings ADD COLUMN learning_score INTEGER NOT NULL DEFAULT 3 CHECK (learning_score BETWEEN 1 AND 5)'],
    ['workload_score', 'ALTER TABLE professor_ratings ADD COLUMN workload_score INTEGER NOT NULL DEFAULT 3 CHECK (workload_score BETWEEN 1 AND 5)'],
    ['exam_difficulty_score', 'ALTER TABLE professor_ratings ADD COLUMN exam_difficulty_score INTEGER NOT NULL DEFAULT 3 CHECK (exam_difficulty_score BETWEEN 1 AND 5)'],
    ['grading_standard_score', 'ALTER TABLE professor_ratings ADD COLUMN grading_standard_score INTEGER NOT NULL DEFAULT 3 CHECK (grading_standard_score BETWEEN 1 AND 5)'],
  ] as const;
  for (const [column, sql] of additions) {
    if (!existing.has(column)) await db.prepare(sql).run();
  }
}

async function ensureCourseHistoryColumns() {
  const db = getD1();
  const tableInfo = await db.prepare('PRAGMA table_info(courses)').all<{ name: string }>();
  if (tableInfo.results.length === 0) return;
  const existing = new Set(tableInfo.results.map((column) => column.name));
  const additions = [
    ['first_term', "ALTER TABLE courses ADD COLUMN first_term TEXT NOT NULL DEFAULT ''"],
    ['last_term', "ALTER TABLE courses ADD COLUMN last_term TEXT NOT NULL DEFAULT ''"],
    ['offered_terms', "ALTER TABLE courses ADD COLUMN offered_terms TEXT NOT NULL DEFAULT ''"],
    ['semester', "ALTER TABLE courses ADD COLUMN semester TEXT NOT NULL DEFAULT ''"],
    ['source_type', "ALTER TABLE courses ADD COLUMN source_type TEXT NOT NULL DEFAULT 'official'"],
    ['submitted_by_user_id', 'ALTER TABLE courses ADD COLUMN submitted_by_user_id TEXT'],
  ] as const;
  for (const [column, sql] of additions) {
    if (!existing.has(column)) await db.prepare(sql).run();
  }
  await db.batch([
    db.prepare(`UPDATE courses SET semester = CASE
      WHEN term LIKE '%-1' THEN '1' WHEN term LIKE '%-2' THEN '2' ELSE semester END
      WHERE semester = ''`),
    db.prepare('CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_identity ON courses(university_id, term, course_code)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_courses_university_semester ON courses(university_id, semester, department, name)'),
  ]);
}

async function ensureCourseRatingDimensions() {
  const db = getD1();
  const tableInfo = await db.prepare('PRAGMA table_info(course_ratings)').all<{ name: string }>();
  if (tableInfo.results.length === 0) return;
  const existing = new Set(tableInfo.results.map((column) => column.name));
  const legacyTable = await db.prepare(`SELECT name FROM sqlite_master
    WHERE type = 'table' AND name = 'course_ratings_legacy_1_to_5'`).first<{ name: string }>();

  if (!existing.has('attendance_frequency_score')) {
    const tableDefinition = await db.prepare(`SELECT sql FROM sqlite_master
      WHERE type = 'table' AND name = 'course_ratings'`).first<{ sql: string | null }>();
    if (!isLegacyCourseRatingOneToFiveSchema([...existing], tableDefinition?.sql)) {
      throw new Error('Unsupported legacy course_ratings schema; refusing to mark it as current.');
    }
    if (legacyTable) {
      throw new Error('Cannot upgrade course_ratings because the legacy backup table already exists.');
    }
    await db.batch(legacyCourseRatingUpgradeStatements.map((statement) => db.prepare(statement)));
    return;
  }

  const currentBaseColumns = ['instructor_name', 'workload_score', 'exam_difficulty_score', 'attendance_frequency_score'];
  if (!currentBaseColumns.every((column) => existing.has(column))) {
    throw new Error('Unsupported course_ratings schema; refusing to mark it as current.');
  }

  const additions = [
    ['learning_score', `ALTER TABLE course_ratings ADD COLUMN learning_score INTEGER CHECK (
      learning_score IS NULL OR (typeof(learning_score) = 'integer' AND learning_score BETWEEN 0 AND 100)
    )`],
    ['grading_standard_score', `ALTER TABLE course_ratings ADD COLUMN grading_standard_score INTEGER CHECK (
      grading_standard_score IS NULL OR (typeof(grading_standard_score) = 'integer' AND grading_standard_score BETWEEN 0 AND 100)
    )`],
  ] as const;
  for (const [column, sql] of additions) {
    if (!existing.has(column)) await db.prepare(sql).run();
  }

  if (legacyTable) {
    await db.prepare(`UPDATE course_ratings
      SET
        learning_score = COALESCE(learning_score, (
          SELECT legacy.learning_score * 20 FROM course_ratings_legacy_1_to_5 AS legacy
          WHERE legacy.id = course_ratings.id
        )),
        grading_standard_score = COALESCE(grading_standard_score, (
          SELECT legacy.grading_standard_score * 20 FROM course_ratings_legacy_1_to_5 AS legacy
          WHERE legacy.id = course_ratings.id
        ))
      WHERE learning_score IS NULL OR grading_standard_score IS NULL`).run();
  }
}

async function ensureUnifiedProfessorIdentities() {
  const db = getD1();
  const identityIndex = await db.prepare(`SELECT sql FROM sqlite_master
    WHERE type = 'index' AND name = 'idx_professors_identity'`).first<{ sql: string | null }>();
  if (identityIndex?.sql && !/department/i.test(identityIndex.sql)) return;

  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS _professor_identity_map (
      old_id TEXT PRIMARY KEY NOT NULL,
      canonical_id TEXT NOT NULL,
      merged_department TEXT NOT NULL
    )`),
    db.prepare('DELETE FROM _professor_identity_map'),
    db.prepare(`INSERT INTO _professor_identity_map (old_id, canonical_id, merged_department)
      SELECT p.id, grouped.canonical_id, grouped.merged_department
      FROM professors p
      JOIN (
        SELECT university_id, name, MIN(id) AS canonical_id,
          REPLACE(GROUP_CONCAT(DISTINCT department), ',', '／') AS merged_department
        FROM professors GROUP BY university_id, name
      ) grouped ON grouped.university_id = p.university_id AND grouped.name = p.name`),
    db.prepare(`CREATE TABLE IF NOT EXISTS _professor_rating_rank (
      rating_id TEXT PRIMARY KEY NOT NULL,
      canonical_id TEXT NOT NULL,
      identity_rank INTEGER NOT NULL
    )`),
    db.prepare('DELETE FROM _professor_rating_rank'),
    db.prepare(`INSERT INTO _professor_rating_rank (rating_id, canonical_id, identity_rank)
      SELECT pr.id, identity_map.canonical_id,
        ROW_NUMBER() OVER (
          PARTITION BY pr.user_id, identity_map.canonical_id
          ORDER BY pr.updated_at DESC, pr.id DESC
        ) AS identity_rank
      FROM professor_ratings pr
      JOIN _professor_identity_map identity_map ON identity_map.old_id = pr.professor_id`),
    db.prepare(`DELETE FROM professor_ratings
      WHERE id IN (SELECT rating_id FROM _professor_rating_rank WHERE identity_rank > 1)`),
    db.prepare(`UPDATE professor_ratings SET professor_id = (
        SELECT canonical_id FROM _professor_rating_rank WHERE rating_id = professor_ratings.id
      ) WHERE id IN (SELECT rating_id FROM _professor_rating_rank WHERE identity_rank = 1)`),
    db.prepare(`DELETE FROM professors WHERE id IN (
      SELECT old_id FROM _professor_identity_map WHERE old_id != canonical_id
    )`),
    db.prepare(`UPDATE professors SET department = (
        SELECT merged_department FROM _professor_identity_map
        WHERE canonical_id = professors.id LIMIT 1
      ), updated_at = CURRENT_TIMESTAMP
      WHERE id IN (SELECT canonical_id FROM _professor_identity_map)`),
    db.prepare('DROP INDEX IF EXISTS idx_professors_identity'),
    db.prepare('CREATE UNIQUE INDEX idx_professors_identity ON professors(university_id, name)'),
    db.prepare('DROP TABLE _professor_rating_rank'),
    db.prepare('DROP TABLE _professor_identity_map'),
  ]);
}

async function runBatches(statements: D1PreparedStatement[], size = 80) {
  const db = getD1();
  for (let index = 0; index < statements.length; index += size) {
    await db.batch(statements.slice(index, index + size));
  }
}

async function runVersionedSeed(options: {
  name: string;
  version: string;
  table: string;
  run: () => Promise<void>;
}) {
  const db = getD1();
  const marker = await db.prepare('SELECT version FROM app_seed_versions WHERE seed_name = ?')
    .bind(options.name).first<{ version: string }>();
  const count = await db.prepare(`SELECT COUNT(*) AS count FROM ${options.table}`).first<{ count: number }>();
  if (marker?.version === options.version && Number(count?.count ?? 0) > 0) return;
  await options.run();
  await db.prepare(`INSERT INTO app_seed_versions (seed_name, version, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(seed_name) DO UPDATE SET version = excluded.version, updated_at = excluded.updated_at`)
    .bind(options.name, options.version).run();
}

async function initializeCoreTables() {
  const db = getD1();
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS academic_departments (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
      college TEXT NOT NULL,
      name TEXT NOT NULL,
      unit_type TEXT NOT NULL CHECK (unit_type IN ('department', 'institute', 'program', 'academic-unit')),
      official_source_url TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (university_id, name)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS professors (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
      department TEXT NOT NULL,
      name TEXT NOT NULL,
      official_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS professor_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      professor_id TEXT NOT NULL REFERENCES professors(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      easy_to_pass_score INTEGER NOT NULL CHECK (easy_to_pass_score BETWEEN 1 AND 5),
      attitude_score INTEGER NOT NULL DEFAULT 3 CHECK (attitude_score BETWEEN 1 AND 5),
      learning_score INTEGER NOT NULL DEFAULT 3 CHECK (learning_score BETWEEN 1 AND 5),
      workload_score INTEGER NOT NULL DEFAULT 3 CHECK (workload_score BETWEEN 1 AND 5),
      exam_difficulty_score INTEGER NOT NULL DEFAULT 3 CHECK (exam_difficulty_score BETWEEN 1 AND 5),
      grading_standard_score INTEGER NOT NULL DEFAULT 3 CHECK (grading_standard_score BETWEEN 1 AND 5),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS courses (
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
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS course_instructors (
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      professor_id TEXT REFERENCES professors(id) ON DELETE SET NULL,
      official_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      PRIMARY KEY (course_id, instructor_name)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS course_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      learning_score INTEGER CHECK (learning_score IS NULL OR (typeof(learning_score) = 'integer' AND learning_score BETWEEN 0 AND 100)),
      workload_score INTEGER NOT NULL CHECK (typeof(workload_score) = 'integer' AND workload_score BETWEEN 0 AND 100),
      exam_difficulty_score INTEGER NOT NULL CHECK (typeof(exam_difficulty_score) = 'integer' AND exam_difficulty_score BETWEEN 0 AND 100),
      grading_standard_score INTEGER CHECK (grading_standard_score IS NULL OR (typeof(grading_standard_score) = 'integer' AND grading_standard_score BETWEEN 0 AND 100)),
      attendance_frequency_score INTEGER CHECK (attendance_frequency_score IS NULL OR (typeof(attendance_frequency_score) = 'integer' AND attendance_frequency_score BETWEEN 0 AND 100)),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (user_id, course_id, instructor_name)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS api_rate_limits (
      user_id TEXT NOT NULL,
      action TEXT NOT NULL,
      window_started_at INTEGER NOT NULL,
      request_count INTEGER NOT NULL DEFAULT 1,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (user_id, action, window_started_at)
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS app_seed_versions (
      seed_name TEXT PRIMARY KEY NOT NULL,
      version TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )`),
  ]);
  await ensureProfessorOfficialSourceUrl();
  await ensureProfessorRatingDimensions();
  await ensureCourseHistoryColumns();
  await ensureCourseRatingDimensions();
  await ensureUnifiedProfessorIdentities();
  await db.batch([
    db.prepare('CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_departments_identity ON academic_departments(university_id, name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_academic_departments_university_college ON academic_departments(university_id, college, name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_academic_departments_name ON academic_departments(name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_professors_university ON professors(university_id)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_professors_department ON professors(department)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_professors_name ON professors(name)'),
    db.prepare('CREATE UNIQUE INDEX IF NOT EXISTS idx_professor_ratings_user_professor ON professor_ratings(user_id, professor_id)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_professor_ratings_professor ON professor_ratings(professor_id)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_professor_ratings_user ON professor_ratings(user_id)'),
    db.prepare('CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_identity ON courses(university_id, term, course_code)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_courses_university_term ON courses(university_id, term, department, name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_courses_name ON courses(name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_courses_department ON courses(department)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_course_instructors_name ON course_instructors(instructor_name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_course_instructors_professor ON course_instructors(professor_id)'),
    db.prepare('CREATE UNIQUE INDEX IF NOT EXISTS idx_course_ratings_user_course_instructor ON course_ratings(user_id, course_id, instructor_name)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_course_ratings_course ON course_ratings(course_id)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_course_ratings_user ON course_ratings(user_id)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_api_rate_limits_cleanup ON api_rate_limits(window_started_at)'),
  ]);
}

async function seedDepartments() {
  const db = getD1();
  const timestamp = '2026-08-27T00:00:00.000Z';
  const statements = departmentSeeds.filter((seed) => activeUniversityIds.has(seed.universityId)).map((seed) => db.prepare(`
    INSERT INTO academic_departments (
      id, university_id, college, name, unit_type, official_source_url, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(university_id, name) DO UPDATE SET
      college = excluded.college,
      unit_type = excluded.unit_type,
      official_source_url = excluded.official_source_url,
      updated_at = excluded.updated_at
  `).bind(
    seed.id, seed.universityId, seed.college, seed.name, seed.unitType,
    seed.sourceUrl, timestamp, timestamp,
  ));
  await runBatches(statements);
}

async function seedProfessors() {
  const db = getD1();
  const timestamp = '2026-08-27T00:00:00.000Z';
  const statements = professorSeeds.filter((seed) => activeUniversityIds.has(seed.universityId)).map((seed) => db.prepare(`
    INSERT INTO professors (
      id, university_id, department, name, official_source_url, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(university_id, name) DO UPDATE SET
      department = excluded.department,
      official_source_url = excluded.official_source_url,
      updated_at = excluded.updated_at
  `).bind(seed.id, seed.universityId, seed.department, seed.name, seed.sourceUrl, timestamp, timestamp));
  await runBatches(statements);
}

async function purgeRemovedUniversityData() {
  const db = getD1();
  for (const universityId of ['ncku', 'nycu-yangming']) {
    await db.batch([
      db.prepare('DELETE FROM course_ratings WHERE course_id IN (SELECT id FROM courses WHERE university_id = ?)').bind(universityId),
      db.prepare('DELETE FROM course_instructors WHERE course_id IN (SELECT id FROM courses WHERE university_id = ?)').bind(universityId),
      db.prepare('DELETE FROM courses WHERE university_id = ?').bind(universityId),
      db.prepare('DELETE FROM professor_ratings WHERE professor_id IN (SELECT id FROM professors WHERE university_id = ?)').bind(universityId),
      db.prepare('DELETE FROM professors WHERE university_id = ?').bind(universityId),
      db.prepare('DELETE FROM academic_departments WHERE university_id = ?').bind(universityId),
      db.prepare('DELETE FROM universities WHERE id = ?').bind(universityId),
    ]);
  }
}

async function removeRentalStorage() {
  const db = getD1();
  await db.batch([
    db.prepare('DROP TABLE IF EXISTS rental_comments'),
    db.prepare('DROP TABLE IF EXISTS rental_reports'),
    db.prepare('DROP TABLE IF EXISTS rental_location_universities'),
    db.prepare('DROP TABLE IF EXISTS rental_locations'),
    db.prepare('DROP TABLE IF EXISTS reviews'),
    db.prepare('DROP TABLE IF EXISTS listings'),
  ]);
  await db.prepare("DELETE FROM app_seed_versions WHERE seed_name = 'rentals'").run();
}

async function initializeDatabase() {
  if (await isRuntimeSchemaReady()) return;
  const db = getD1();
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS universities (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL,
      short_name TEXT NOT NULL,
      city TEXT NOT NULL,
      district TEXT NOT NULL,
      latitude REAL NOT NULL,
      longitude REAL NOT NULL,
      address TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY NOT NULL,
      google_sub TEXT NOT NULL UNIQUE,
      email TEXT NOT NULL,
      name TEXT NOT NULL,
      avatar_url TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS auth_sessions (
      id TEXT PRIMARY KEY NOT NULL,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL
    )`),
  ]);

  await ensureUniversityCreatedAt();

  await db.batch([
    db.prepare('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)'),
    db.prepare('CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_expires ON auth_sessions(user_id, expires_at)'),
  ]);

  const schoolSeeds = universities.map((school) => db.prepare(`
    INSERT INTO universities
      (id, name, short_name, city, district, latitude, longitude, address, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      short_name = excluded.short_name,
      city = excluded.city,
      district = excluded.district,
      latitude = excluded.latitude,
      longitude = excluded.longitude,
      address = excluded.address,
      created_at = COALESCE(universities.created_at, excluded.created_at)
  `).bind(school.id, school.name, school.shortName, school.city, school.district, school.latitude, school.longitude, school.address, '2026-08-26T00:00:00.000Z'));
  await db.batch(schoolSeeds);

  await initializeCoreTables();
  await removeRentalStorage();
  await purgeRemovedUniversityData();
  await runVersionedSeed({ name: 'departments', version: '2026-08-27-v1', table: 'academic_departments', run: seedDepartments });
  await runVersionedSeed({ name: 'professors', version: '2026-08-27-v1', table: 'professors', run: seedProfessors });
  await db.prepare(`CREATE TABLE IF NOT EXISTS app_runtime_state (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )`).run();
  await db.prepare(`INSERT INTO app_runtime_state (key, value, updated_at)
    VALUES ('schema_version', ?, CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`)
    .bind(runtimeSchemaVersion).run();
  await db.prepare('PRAGMA optimize').run();
}

export function ensureDatabase() {
  if (!databaseReady) {
    databaseReady = initializeDatabase().catch((error) => {
      databaseReady = null;
      throw error;
    });
  }
  return databaseReady;
}
