import { readFileSync, readdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

const migrationFiles = readdirSync(new URL('../drizzle/', import.meta.url))
  .filter((name) => /^\d{4}_.+\.sql$/.test(name))
  .sort();
const universityIds = [...readFileSync(new URL('../app/data.ts', import.meta.url), 'utf8')
  .matchAll(/\bid:\s*'([a-z0-9-]+)'/g)].map((match) => match[1]);

// Replay the committed migration chain instead of opening whichever stale
// Miniflare file happens to appear first in .wrangler.  The result is
// deterministic and matches the schema/data that a clean deployment receives.
const database = new DatabaseSync(':memory:');
database.exec('PRAGMA foreign_keys = ON');
database.exec('BEGIN');
try {
  for (const file of migrationFiles) {
    const statements = readFileSync(new URL(`../drizzle/${file}`, import.meta.url), 'utf8')
      .split('--> statement-breakpoint')
      .map((statement) => statement.trim())
      .filter(Boolean);
    for (const statement of statements) database.exec(statement);
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

const indexes = database.prepare("SELECT name FROM sqlite_schema WHERE type = 'index' AND name NOT LIKE 'sqlite_%' ORDER BY name").all();
const counts = database.prepare(`SELECT
  (SELECT COUNT(*) FROM universities) AS universities,
  (SELECT COUNT(*) FROM academic_departments) AS academicDepartments,
  (SELECT COUNT(*) FROM professors) AS professors,
  (SELECT COUNT(*) FROM courses) AS courses,
  (SELECT COUNT(*) FROM course_instructors) AS courseInstructors,
  (SELECT COUNT(*) FROM course_ratings) AS courseRatings,
  (SELECT COUNT(*) FROM users) AS users`).get();
const coursePlan = database.prepare(`EXPLAIN QUERY PLAN SELECT id FROM courses
  WHERE university_id = ? AND semester = ? AND department = ? ORDER BY name LIMIT 36`)
  .all('ntu', '1', '資訊工程學系');
const ratingPlan = database.prepare(`EXPLAIN QUERY PLAN SELECT AVG(workload_score) FROM course_ratings
  WHERE course_id = ? AND instructor_name = ?`).all('course-id', '教師');

console.log(JSON.stringify({ source: 'fresh-migration-replay', indexes, counts, coursePlan, ratingPlan }, null, 2));
database.close();
