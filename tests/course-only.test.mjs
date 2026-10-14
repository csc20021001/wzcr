import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const schema = readFileSync(new URL('../db/schema.ts', import.meta.url), 'utf8');
const databaseRuntime = readFileSync(new URL('../db/index.ts', import.meta.url), 'utf8');
const migration = readFileSync(new URL('../drizzle/0050_remove_rentals.sql', import.meta.url), 'utf8');

function apply(database, sql) {
  for (const statement of sql.split('--> statement-breakpoint').map((value) => value.trim()).filter(Boolean)) {
    database.exec(statement);
  }
}

test('course-only bundle has no map dependency or rental schema', () => {
  assert.equal(packageJson.dependencies['maplibre-gl'], undefined);
  assert.doesNotMatch(schema, /sqliteTable\('(rental_|listings|reviews)/);
  assert.doesNotMatch(databaseRuntime, /CREATE TABLE IF NOT EXISTS (rental_|listings|reviews)/);
  assert.match(databaseRuntime, /DROP TABLE IF EXISTS rental_locations/);
});

test('course-only migration deletes rental storage without touching courses', () => {
  const database = new DatabaseSync(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE courses (id TEXT PRIMARY KEY NOT NULL, university_id TEXT NOT NULL);
    CREATE TABLE listings (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE reviews (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE rental_locations (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE rental_location_universities (rental_location_id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE rental_reports (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE rental_comments (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE api_rate_limits (user_id TEXT, action TEXT, window_started_at INTEGER, request_count INTEGER, updated_at TEXT);
    CREATE TABLE app_seed_versions (seed_name TEXT PRIMARY KEY NOT NULL, version TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE app_runtime_state (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    INSERT INTO universities VALUES ('ntu'), ('nycu-yangming');
    INSERT INTO courses VALUES ('course-1', 'ntu');
    INSERT INTO rental_locations VALUES ('rental-1');
    INSERT INTO app_seed_versions VALUES ('rentals', 'old', 'now'), ('professors', 'current', 'now');
    INSERT INTO app_runtime_state VALUES ('schema_version', 'old', 'now');
  `);

  apply(database, migration);

  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM courses").get().count, 1);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM universities WHERE id = 'nycu-yangming'").get().count, 0);
  assert.equal(database.prepare("SELECT COUNT(*) AS count FROM app_seed_versions WHERE seed_name = 'rentals'").get().count, 0);
  assert.equal(database.prepare("SELECT value FROM app_runtime_state WHERE key = 'schema_version'").get().value, '2026-08-29-course-only-v1');
  for (const table of ['listings', 'reviews', 'rental_locations', 'rental_location_universities', 'rental_reports', 'rental_comments']) {
    assert.equal(database.prepare("SELECT COUNT(*) AS count FROM sqlite_schema WHERE type = 'table' AND name = ?").get(table).count, 0, table);
  }
  database.close();
});
