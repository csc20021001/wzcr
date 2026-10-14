import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const migrationFiles = readdirSync(new URL('../drizzle/', import.meta.url))
  .filter((name) => /^\d{4}_.+\.sql$/.test(name))
  .sort();
const universityIds = [...readFileSync(new URL('../app/data.ts', import.meta.url), 'utf8')
  .matchAll(/\bid:\s*'([a-z0-9-]+)'/g)].map((match) => match[1]);

function statements(name) {
  return readFileSync(new URL(`../drizzle/${name}`, import.meta.url), 'utf8')
    .split('--> statement-breakpoint')
    .map((statement) => statement.trim())
    .filter(Boolean);
}

test('every migration applies in order to a fresh SQLite database', { timeout: 120_000 }, () => {
  const database = new DatabaseSync(':memory:');
  database.exec('PRAGMA foreign_keys = ON');
  database.exec('BEGIN');
  try {
    for (const file of migrationFiles) {
      for (const statement of statements(file)) {
        try {
          database.exec(statement);
        } catch (error) {
          throw new Error(`${file}: ${error.message}`, { cause: error });
        }
      }
      // The application has always seeded its university directory at runtime;
      // early rental migrations therefore legitimately reference these rows.
      if (file === '0002_auth_and_publishing.sql') {
        const insert = database.prepare(`INSERT OR IGNORE INTO universities
          (id, name, short_name, city, district, latitude, longitude, address)
          VALUES (?, ?, ?, '', '', 0, 0, '')`);
        for (const id of universityIds) insert.run(id, id, id);
      }
    }
    database.exec('COMMIT');
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  }

  const tables = new Set(database.prepare(
    "SELECT name FROM sqlite_schema WHERE type='table'",
  ).all().map((row) => row.name));
  const ratingColumns = new Set(database.prepare('PRAGMA table_info(course_ratings)')
    .all().map((column) => column.name));
  const courseCount = database.prepare('SELECT COUNT(*) AS count FROM courses').get().count;

  assert.ok(courseCount > 70_000, `expected a material course snapshot, received ${courseCount}`);
  assert.equal(tables.has('rental_listings'), false);
  for (const column of [
    'learning_score',
    'workload_score',
    'exam_difficulty_score',
    'grading_standard_score',
    'attendance_frequency_score',
  ]) assert.ok(ratingColumns.has(column), `missing rating column ${column}`);
  database.close();
});
