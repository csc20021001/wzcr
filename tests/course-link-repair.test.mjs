import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const migration = readFileSync(new URL('../drizzle/0051_complete_official_course_links.sql', import.meta.url), 'utf8');
const runtime = readFileSync(new URL('../db/index.ts', import.meta.url), 'utf8');
const officialImporter = readFileSync(new URL('../scripts/import-official-course-history.py', import.meta.url), 'utf8');
const privateImporter = readFileSync(new URL('../scripts/import-four-private-universities.py', import.meta.url), 'utf8');

test('course link repair is update-only, complete, and executable', () => {
  assert.equal((migration.match(/^UPDATE courses SET department_source_url/gm) ?? []).length, 827);
  assert.equal((migration.match(/^UPDATE academic_departments SET official_source_url/gm) ?? []).length, 827);
  assert.doesNotMatch(migration, /\bDELETE\b|\bDROP\b/);
  assert.match(migration, /2026-08-29-course-links-v1/);
  assert.match(runtime, /runtimeSchemaVersion = '2026-08-29-course-rating-five-dimensions-v1'/);
  assert.match(runtime, /async function ensureCourseRatingDimensions\(\)/);
  assert.match(runtime, /course_ratings_legacy_1_to_5/);

  const database = new DatabaseSync(':memory:');
  database.exec(`
    CREATE TABLE courses (
      id TEXT PRIMARY KEY,
      university_id TEXT NOT NULL,
      department TEXT NOT NULL,
      department_source_url TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE academic_departments (
      id TEXT PRIMARY KEY,
      university_id TEXT NOT NULL,
      name TEXT NOT NULL,
      official_source_url TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE app_runtime_state (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    INSERT INTO courses VALUES ('course-1', 'ccu', '中國文學系', 'https://example.invalid/', 'before');
    INSERT INTO academic_departments VALUES ('dept-1', 'ccu', '中國文學系', 'https://example.invalid/', 'before');
  `);
  for (const statement of migration.split('--> statement-breakpoint').map((value) => value.trim()).filter(Boolean)) {
    database.exec(statement);
  }
  assert.equal(database.prepare("SELECT department_source_url AS url FROM courses WHERE id = 'course-1'").get().url, 'https://litera.ccu.edu.tw/');
  assert.equal(database.prepare("SELECT official_source_url AS url FROM academic_departments WHERE id = 'dept-1'").get().url, 'https://litera.ccu.edu.tw/');
  assert.equal(database.prepare("SELECT value FROM app_runtime_state WHERE key = 'schema_version'").get().value, '2026-08-29-course-links-v1');
  database.close();
});

test('importers prefer official department sites and use official directories as fallback', () => {
  assert.match(officialImporter, /row\.get\("websiteUrl"\) or row\.get\("officialDirectoryUrl"\)/);
  assert.match(officialImporter, /_DEPARTMENT_URL_CACHE/);
  assert.match(privateImporter, /OFFICIAL_DEPARTMENT_DIRECTORIES/);
  assert.match(privateImporter, /load_official_department_links/);
  assert.match(privateImporter, /resolve_department_url/);
  assert.match(privateImporter, /Rejected non-official URL/);
});
