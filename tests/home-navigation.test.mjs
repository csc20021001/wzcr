import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const home = readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8');
const courseDirectory = readFileSync(new URL('../app/courses/course-directory.tsx', import.meta.url), 'utf8');

test('homepage immediately opens the course directory', () => {
  assert.match(home, /redirect\('\/courses'\)/);
  assert.doesNotMatch(home, /租屋|查房子|rentals/i);
});

test('course header no longer links back to rental features', () => {
  assert.match(courseDirectory, /WZUNAA 課程評分/);
  assert.match(courseDirectory, /新增課程/);
  assert.match(courseDirectory, /五項課程評分/);
  assert.doesNotMatch(courseDirectory, /回租屋地圖|href="\/rentals"/);
});

test('course directory waits for each visitor to choose a university', () => {
  assert.match(courseDirectory, /const \[schoolId, setSchoolId\] = useState\(''\)/);
  assert.match(courseDirectory, /<option value="">請選擇學校<\/option>/);
  assert.match(courseDirectory, /!schoolId && <div className="professor-empty professor-school-prompt"/);
  assert.doesNotMatch(courseDirectory, /useState\('ntu'\)/);
});

test('rental page and APIs are removed from the application', () => {
  for (const path of [
    '../app/rentals/page.tsx',
    '../app/api/rentals/route.ts',
    '../app/api/listings/route.ts',
    '../app/api/reviews/route.ts',
  ]) {
    assert.equal(existsSync(new URL(path, import.meta.url)), false, path);
  }
});
