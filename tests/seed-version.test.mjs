import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const database = readFileSync(new URL('../db/index.ts', import.meta.url), 'utf8');
const migration = readFileSync(new URL('../drizzle/0021_runtime_seed_versions.sql', import.meta.url), 'utf8');
const schemaState = readFileSync(new URL('../drizzle/0022_runtime_schema_state.sql', import.meta.url), 'utf8');

test('large runtime seeds are versioned and skipped after successful import', () => {
  assert.match(database, /runVersionedSeed/);
  assert.match(database, /marker\?\.version === options\.version/);
  assert.match(database, /Number\(count\?\.count \?\? 0\) > 0/);
  for (const seed of ['departments', 'professors']) {
    assert.match(migration, new RegExp(`'${seed}'`));
  }
  assert.doesNotMatch(database, /runVersionedSeed\(\{ name: 'rentals'/);
});

test('cold starts use one guarded schema-state query and retain a missing-data fallback', () => {
  assert.match(database, /if \(await isRuntimeSchemaReady\(\)\) return/);
  assert.match(database, /Number\(state\.course_count\) > 0/);
  assert.match(database, /catch \{\s+return false/);
  assert.match(schemaState, /'schema_version', '2026-08-28-v1'/);
  assert.match(database, /2026-08-29-course-rating-five-dimensions-v1/);
});
