import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import test from 'node:test';

const report = JSON.parse(readFileSync(new URL('../db/place-name-course-report.generated.json', import.meta.url), 'utf8'));
const importer = readFileSync(new URL('../scripts/import-place-name-universities.py', import.meta.url), 'utf8');
const webforms = readFileSync(new URL('../scripts/fetch-official-webforms.mjs', import.meta.url), 'utf8');
const appData = readFileSync(new URL('../app/data.ts', import.meta.url), 'utf8');

function pythonFunction(name) {
  const marker = `def ${name}(`;
  const start = importer.indexOf(marker);
  assert.notEqual(start, -1, `missing Python function ${name}`);
  const next = importer.indexOf('\ndef ', start + marker.length);
  return importer.slice(start, next === -1 ? importer.length : next);
}

const placeNamePublicUniversities = [
  'ntu', 'ntnu', 'ntou', 'nknu', 'ncue', 'ntpu', 'ncyu', 'nuk', 'ntust', 'yuntech',
  'npust', 'ntut', 'tnua', 'ntua', 'nttu', 'niu', 'nfu', 'tnnua', 'nutn', 'ntue',
  'ntcu', 'npu', 'ntunhs', 'nkuht', 'nqu', 'ntus', 'nutc', 'ntub', 'nptu', 'nkust',
  'utaipei', 'nou',
];

test('all 32 public place-name universities are selectable without duplicate ids', () => {
  const ids = [...appData.matchAll(/\bid:\s*'([a-z0-9-]+)'/g)].map((match) => match[1]);
  assert.equal(ids.length, new Set(ids).size);
  for (const id of placeNamePublicUniversities) assert.ok(ids.includes(id), `missing university ${id}`);
});

test('place-name course report is material, audited, and migration-sized', () => {
  assert.equal(report.policy.officialUniversityDomainsOnly, true);
  assert.equal(report.policy.requiresCurrentOfficialScheduleEvidence, true);
  assert.equal(report.policy.inactiveOrUnverifiedInstructorsPublished, false);
  assert.ok(report.courseCount > 40_000);
  assert.equal(report.schools.length, 28);
  assert.equal(new Set(report.schools.map((school) => school.universityId)).size, 28);
  for (const id of ['nknu', 'nptu', 'ntpu', 'tnnua', 'ntcu', 'ntou', 'ntue', 'nttu', 'ntub', 'ntunhs', 'ntus', 'tnua', 'ncue', 'ncyu', 'yuntech', 'utaipei', 'nutc', 'npust']) {
    const school = report.schools.find((entry) => entry.universityId === id);
    assert.ok(school, `missing report for ${id}`);
    assert.ok(school.verifiedCourses > 0, `${id} has no verified courses`);
    assert.ok(school.currentRosterEvidenceTerms.length > 0, `${id} lacks current roster evidence`);
  }
  // A school without published courses must say why, never fail silently.
  for (const school of report.schools) {
    if (school.verifiedCourses > 0) continue;
    assert.ok(
      ['restricted', 'unreachable'].includes(school.status),
      `${school.universityId} publishes no courses without an audited status`,
    );
    assert.ok(school.note, `${school.universityId} publishes no courses without a reason`);
  }
  for (const file of report.migrationFiles) {
    const size = statSync(new URL(`../drizzle/${file}`, import.meta.url)).size;
    assert.ok(size < 900 * 1024, `${file} exceeds the repository migration limit`);
  }
});

test('official fetchers fail closed and preserve TLS verification', () => {
  assert.doesNotMatch(importer, /verify\s*=\s*False|_create_unverified_context|CERT_NONE/);
  assert.doesNotMatch(webforms, /http:\/\//);
  assert.match(importer, /official_url\(school_id, url\)/);
  assert.match(importer, /requiresCurrentOfficialScheduleEvidence/);
  assert.match(importer, /is_excluded_course/);
  assert.match(webforms, /parsed\.protocol !== 'https:'/);
});

test('generated migration batches are immutable after commit but uncommitted batches can regenerate', () => {
  const committedNames = pythonFunction('committed_migration_names');
  const writeMigrations = pythonFunction('write_migrations');
  assert.match(committedNames, /git["'],\s*["']ls-tree["']/);
  assert.match(committedNames, /["']HEAD["']/);
  assert.match(writeMigrations, /committed_batch/);
  assert.match(writeMigrations, /pass a new --batch-id/);
  assert.ok(
    writeMigrations.indexOf('if committed_batch:') < writeMigrations.indexOf('path.unlink()'),
    'the committed-batch guard must run before deleting a generated migration',
  );
  assert.match(writeMigrations, /current_batch = list\(MIGRATIONS\.glob\(pattern\)\)/);
});

test('course names publish the official first line of a stacked schedule cell', () => {
  const cleaner = pythonFunction('official_course_name');
  const dedupe = pythonFunction('deduplicate');
  assert.match(importer, /CELL_LINE_BREAK = re\.compile/);
  assert.match(importer, /MERGED_CLASS_NOTE = re\.compile/);
  assert.match(cleaner, /CELL_LINE_BREAK\.split\(normalize_space\(value\), 1\)\[0\]/);
  assert.match(cleaner, /MERGED_CLASS_NOTE\.sub/);
  assert.match(dedupe, /"name": official_course_name\(row\["name"\]\)/);
  assert.match(dedupe, /if not row\["name"\] or is_excluded_course/);
});

test('a follow-up batch only rebuilds the schools it actually imported', () => {
  const writeMigrations = pythonFunction('write_migrations');
  assert.match(writeMigrations, /target_schools: tuple\[str, \.\.\.\] = \(\)/);
  assert.match(writeMigrations, /target_schools = tuple\(sorted\(target_schools or SCHOOLS\)\)/);
  assert.match(writeMigrations, /unknown target schools/);
  assert.match(importer, /"--only"/);
  assert.match(importer, /"--batch-id"/);
  assert.match(importer, /target_schools=tuple\(targets\)/);
  const merge = pythonFunction('merge_report');
  assert.match(merge, /report\["universityId"\] not in covered/);
  assert.ok(
    Array.isArray(report.batchSchools) === false || report.batchSchools.every((id) => typeof id === 'string'),
  );
});

test('migration rebuilds official instructor links without deleting rated course parents', () => {
  const writeMigrations = pythonFunction('write_migrations');
  const instructorDeleteStart = writeMigrations.indexOf('DELETE FROM course_instructors');
  const instructorDeleteEnd = writeMigrations.indexOf('--> statement-breakpoint', instructorDeleteStart);
  assert.notEqual(instructorDeleteStart, -1);
  assert.notEqual(instructorDeleteEnd, -1);
  const instructorDelete = writeMigrations.slice(instructorDeleteStart, instructorDeleteEnd);
  assert.match(instructorDelete, /c\.source_type='official'/);
  assert.doesNotMatch(instructorDelete, /NOT EXISTS|course_ratings/);
  assert.match(
    writeMigrations,
    /DELETE FROM courses[^\n]+source_type='official'[^\n]+NOT EXISTS[^\n]+course_ratings/s,
  );
  assert.ok(
    writeMigrations.indexOf('DELETE FROM course_instructors')
      < writeMigrations.indexOf('INSERT INTO course_instructors'),
  );
});

test('current roster caches expire while historical cache objects remain reusable', () => {
  const cacheClassifier = pythonFunction('cache_filename_is_current');
  const cacheReusable = pythonFunction('cache_entry_is_reusable');
  const cachedRequest = pythonFunction('cached_request');
  const cachedOpenerRequest = pythonFunction('cached_opener_request');
  const webformsCache = pythonFunction('ensure_webforms_cache');
  assert.match(importer, /CURRENT_CACHE_MAX_AGE_SECONDS\s*=\s*6 \* 60 \* 60/);
  assert.match(cacheClassifier, /CURRENT_YEAR/);
  assert.match(cacheClassifier, /npu-\{CURRENT_YEAR\}-all\.html/);
  assert.match(cacheReusable, /if not cache_filename_is_current\(filename\):\s+return True/);
  assert.match(cacheReusable, /path\.stat\(\)\.st_mtime/);
  assert.match(cacheReusable, /CURRENT_CACHE_MAX_AGE_SECONDS/);
  assert.match(cachedRequest, /cache_entry_is_reusable\(path, filename, minimum_size\)/);
  assert.match(cachedOpenerRequest, /cache_entry_is_reusable\(path, filename, minimum_size\)/);
  assert.match(webformsCache, /cache_entry_is_reusable\(manifest_path, manifest_path\.name, 1\)/);
  assert.match(webformsCache, /cache_entry_is_reusable\(path, path\.name, 1_000\)/);
  assert.match(pythonFunction('nkuht_class_pages'), /cache_entry_is_reusable\(cache_path/);
});

test('TNNUA derives the syllabus CSN from the course-name control', () => {
  const tnnuaRows = pythonFunction('tnnua_term_rows');
  assert.match(importer, /self\._cell is not None and values\.get\("onclick"\)/);
  assert.match(tnnuaRows, /cells\[3\]\["links"\]/);
  assert.match(tnnuaRows, /Print_Course_Syllabus/);
  assert.match(tnnuaRows, /detail_match\.group\(2\) != term/);
  assert.doesNotMatch(tnnuaRows, /cells\[13\]\["links"\]|Show_Registed_Detail/);
});

test('NKUHT departments come from official selector headings instead of class-name guesses', () => {
  const selector = pythonFunction('nkuht_class_selector_items');
  const termRows = pythonFunction('nkuht_term_rows');
  const classPages = pythonFunction('nkuht_class_pages');
  assert.match(selector, /margin-left\\s\*:\\s\*15/);
  assert.match(selector, /current_department = heading/);
  assert.match(selector, /lacks an official department heading/);
  assert.match(termRows, /nkuht_class_selector_items\(term, class_payload\)/);
  assert.match(classPages, /nkuht_parse_page\(term, department, payload\)/);
  assert.doesNotMatch(importer, /def nkuht_department_name\(/);
});
