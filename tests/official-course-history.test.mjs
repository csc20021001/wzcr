import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import test from 'node:test';

const report = JSON.parse(readFileSync(new URL('../db/course-import-report.generated.json', import.meta.url), 'utf8'));
const importer = readFileSync(new URL('../scripts/import-official-course-history.py', import.meta.url), 'utf8');

test('historical course import is material and records its coverage', () => {
  assert.equal(report.baseSnapshotCourseCount, 37625);
  assert.ok(report.courseCount > report.baseSnapshotCourseCount);
  assert.ok(report.completionCourseCount > 0);
  assert.equal(report.policy.officialUniversityDomainsOnly, true);
  assert.equal(report.policy.requiresCurrentOfficialFacultyEvidence, true);
  assert.ok(report.courseMigrationFiles.length > 1);
  assert.ok(report.completionMigrationFiles.length > 1);
  for (const file of report.courseMigrationFiles) {
    const size = statSync(new URL(`../drizzle/${file}`, import.meta.url)).size;
    assert.ok(size < 6.1 * 1024 * 1024, `${file} is too large for the source repository`);
  }
  assert.match(importer, /active_rows = \[active\[teacher\] for teacher in teachers if teacher in active\]/);
  assert.match(importer, /official_url\(university_id, seed\["officialSourceUrl"\]\)/);

  const niu = report.schools.find((school) => school.universityId === 'niu');
  assert.equal(niu.status, 'imported');
  assert.equal(niu.verifiedOfferings, 4401);
  assert.deepEqual(niu.availableTerms, [
    '106-1', '106-2', '107-1', '107-2', '108-1', '108-2', '109-1', '109-2',
    '110-1', '110-2', '111-1', '111-2', '112-1', '112-2', '113-1', '113-2',
    '114-1', '114-2', '115-1',
  ]);
  assert.deepEqual(niu.missingTerms, []);
  assert.deepEqual(report.niuMigrationFiles, ['0052_niu_official_course_history_part_01.sql']);
  assert.match(importer, /TKE5010_01\.aspx/);
  assert.match(importer, /"專題研究" in name/);
});
