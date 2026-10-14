import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

const importer = readFileSync(new URL('../scripts/import-official-course-history.py', import.meta.url), 'utf8');
const placeImporter = readFileSync(new URL('../scripts/import-place-name-universities.py', import.meta.url), 'utf8');
const completionMigration = readFileSync(
  new URL('../drizzle/0055_complete_official_course_coverage_part_01.sql', import.meta.url),
  'utf8',
);

test('official course import never reads course data from non-university hosts', () => {
  assert.doesNotMatch(importer, /nycu\.one|githubusercontent\.com|coursehero\.com|coursenote\.tw/i);
  assert.match(importer, /official_university_for_url\(url\)/);
  assert.match(importer, /sitemap_url = f"\{NYCU_OFFICIAL_SITE\}\/sitemap/);
  assert.match(importer, /nycu_course_page/);
  assert.doesNotMatch(placeImporter, /591|rent\.591|dcard|ptt|coursehero/i);
});

test('deployed base migrations are immutable and coverage refresh preserves ratings', () => {
  assert.match(importer, /deployed migrations are never rewritten/);
  assert.doesNotMatch(importer, /glob\("\[0-9\]\[0-9\]\[0-9\]\[0-9\]_official_course_history/);
  assert.doesNotMatch(importer, /glob\("\[0-9\]\[0-9\]\[0-9\]\[0-9\]_niu_official_course_history/);
  assert.match(importer, /NOT EXISTS \(SELECT 1 FROM course_ratings cr WHERE cr\.course_id = c\.id\)/);
  assert.match(placeImporter, /Preserve every published rating/);
  assert.doesNotMatch(placeImporter, /DELETE FROM course_ratings/);
});

test('completion cleanup cannot delete user courses or ratings from schools outside its batch', () => {
  const generatorStart = importer.indexOf('def write_completion_migrations');
  const generatorEnd = importer.indexOf('\ndef main()', generatorStart);
  const cleanupTemplates = importer
    .slice(generatorStart, generatorEnd)
    .split('\n')
    .filter((line) => line.includes('DELETE FROM') && line.includes('%專題研究%'));
  assert.equal(cleanupTemplates.length, 3);
  for (const template of cleanupTemplates) {
    assert.match(template, /university_id IN \(\{school_list\}\)/);
    assert.match(template, /source_type = 'official'/);
  }

  const database = new DatabaseSync(':memory:');
  database.exec('PRAGMA foreign_keys = ON');
  database.exec(`
    CREATE TABLE courses (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL,
      name TEXT NOT NULL,
      source_type TEXT NOT NULL
    );
    CREATE TABLE course_instructors (
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      PRIMARY KEY (course_id, instructor_name)
    );
    CREATE TABLE course_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE
    );
  `);
  const fixtures = [
    ['outside-official-special', 'ccu', '校外專題研究', 'official'],
    ['target-user-special', 'nchu', '使用者專題研究', 'user'],
    ['target-official-special', 'nchu', '官方專題研究', 'official'],
    ['target-official-normal', 'nchu', '一般課程', 'official'],
  ];
  const insertCourse = database.prepare('INSERT INTO courses VALUES (?, ?, ?, ?)');
  const insertInstructor = database.prepare('INSERT INTO course_instructors VALUES (?, ?)');
  const insertRating = database.prepare('INSERT INTO course_ratings VALUES (?, ?)');
  for (const [id, universityId, name, sourceType] of fixtures) {
    insertCourse.run(id, universityId, name, sourceType);
    insertInstructor.run(id, '測試教師');
    insertRating.run(`rating-${id}`, id);
  }

  const cleanup = completionMigration
    .split('--> statement-breakpoint')
    .slice(0, 3)
    .map((statement) => statement.trim())
    .filter(Boolean);
  for (const statement of cleanup) database.exec(statement);

  const exists = (table, idColumn, id) => database
    .prepare(`SELECT EXISTS(SELECT 1 FROM ${table} WHERE ${idColumn} = ?) AS found`)
    .get(id).found;
  for (const id of ['outside-official-special', 'target-user-special', 'target-official-normal']) {
    assert.equal(exists('courses', 'id', id), 1, `${id} course must survive cleanup`);
    assert.equal(exists('course_ratings', 'id', `rating-${id}`), 1, `${id} rating must survive cleanup`);
  }
  assert.equal(exists('courses', 'id', 'target-official-special'), 0);
  assert.equal(exists('course_ratings', 'id', 'rating-target-official-special'), 0);
  database.close();
});

test('completion migration batches are immutable and allocate collision-free future numbers', () => {
  const committedNamesStart = importer.indexOf('def committed_migration_names');
  const committedNamesEnd = importer.indexOf('\ndef write_course_migrations', committedNamesStart);
  const committedNames = importer.slice(committedNamesStart, committedNamesEnd);
  const start = importer.indexOf('def write_completion_migrations');
  const end = importer.indexOf('\ndef main()', start);
  const generator = importer.slice(start, end);
  assert.match(importer, /COMPLETION_MIGRATION_BATCH\s*=\s*\d+/);
  assert.match(committedNames, /git["'],\s*["']ls-tree["']/);
  assert.match(committedNames, /["']HEAD["']/);
  assert.match(generator, /committed_batch/);
  assert.match(generator, /bump COMPLETION_MIGRATION_BATCH/);
  assert.ok(
    generator.indexOf('if committed_batch:') < generator.indexOf('path.unlink()'),
    'the committed-batch guard must run before deleting a generated migration',
  );
  assert.match(generator, /start_number = min\(current_numbers\) if current_numbers else max\(other_numbers, default=0\) \+ 1/);
  assert.ok(
    generator.indexOf('if collisions:') < generator.indexOf('path.unlink()'),
    'number collisions must be rejected before regenerating an uncommitted batch',
  );

  const migrationNumbers = readdirSync(new URL('../drizzle/', import.meta.url))
    .map((name) => /^(\d{4})_.*\.sql$/.exec(name)?.[1])
    .filter(Boolean);
  assert.equal(migrationNumbers.length, new Set(migrationNumbers).size, 'migration numbers must be unique');
});

test('all course import paths exclude special research courses before migrations', () => {
  assert.match(importer, /if "專題研究" in normalize_space\(row\.get\("name"\)\)/);
  assert.match(placeImporter, /"專題研究" in text/);
  assert.match(placeImporter, /"special research project" in text/);
});
