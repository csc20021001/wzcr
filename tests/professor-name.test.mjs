import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const importer = readFileSync(new URL('../scripts/import-official-course-history.py', import.meta.url), 'utf8');
const courseDirectory = readFileSync(new URL('../app/courses/course-directory.tsx', import.meta.url), 'utf8');

test('course instructors use full public names without masking', () => {
  assert.match(importer, /"name": name/);
  assert.match(courseDirectory, /instructor\.name/);
  assert.doesNotMatch(courseDirectory, /maskProfessorName|○/);
});

test('course UI explains all five rating directions', () => {
  assert.match(courseDirectory, /越高代表越能學到東西/);
  assert.match(courseDirectory, /越高代表作業越多/);
  assert.match(courseDirectory, /越高代表考試越難/);
  assert.match(courseDirectory, /越高代表給分越寬鬆/);
  assert.match(courseDirectory, /越高代表越常點名/);
  assert.match(courseDirectory, /送出五項課程評分/);
});
