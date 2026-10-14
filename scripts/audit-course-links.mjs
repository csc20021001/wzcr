import { readFileSync, writeFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

const root = new URL('../', import.meta.url);
const readJson = (path) => JSON.parse(readFileSync(new URL(path, root), 'utf8'));
const readMigration = (name) => readFileSync(new URL(`drizzle/${name}`, root), 'utf8')
  .split('--> statement-breakpoint')
  .map((statement) => statement.trim())
  .filter(Boolean);

const officialReport = readJson('db/course-import-report.generated.json');
const privateReport = readJson('db/four-school-course-report.generated.json');
const universityIds = [
  'ntu', 'nthu', 'nycu', 'ncu', 'nchu', 'ccu', 'nsysu', 'ntust', 'ntut', 'niu',
  'cycu', 'tku', 'yzu', 'fcu',
];

const database = new DatabaseSync(':memory:');
database.exec('PRAGMA foreign_keys = ON');
database.exec(`
  CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
  CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL);
  CREATE TABLE professors (
    id TEXT PRIMARY KEY NOT NULL,
    university_id TEXT NOT NULL REFERENCES universities(id),
    name TEXT NOT NULL
  );
  CREATE TABLE academic_departments (
    id TEXT PRIMARY KEY NOT NULL,
    university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
    college TEXT NOT NULL,
    name TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    official_source_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (university_id, name)
  );
`);
const insertUniversity = database.prepare('INSERT INTO universities (id) VALUES (?)');
for (const id of universityIds) insertUniversity.run(id);

database.exec('BEGIN');
try {
  for (const name of [
    '0013_courses_and_course_ratings.sql',
    '0014_course_history_terms.sql',
    ...officialReport.courseMigrationFiles,
  ]) {
    for (const statement of readMigration(name)) database.exec(statement);
  }
  database.exec("ALTER TABLE courses ADD COLUMN semester TEXT NOT NULL DEFAULT ''");
  database.exec("ALTER TABLE courses ADD COLUMN source_type TEXT NOT NULL DEFAULT 'official'");
  database.exec('ALTER TABLE courses ADD COLUMN submitted_by_user_id TEXT');
  for (const name of privateReport.migrationFiles) {
    for (const statement of readMigration(name)) database.exec(statement);
  }
  database.exec('COMMIT');
} catch (error) {
  database.exec('ROLLBACK');
  throw error;
}

const rows = database.prepare(`
  SELECT
    university_id AS universityId,
    COUNT(*) AS courses,
    COUNT(DISTINCT department) AS departments,
    SUM(CASE WHEN TRIM(official_source_url) = '' THEN 1 ELSE 0 END) AS missingCourseLinks,
    SUM(CASE WHEN TRIM(department_source_url) = '' THEN 1 ELSE 0 END) AS missingDepartmentLinks,
    SUM(CASE WHEN official_source_url = department_source_url THEN 1 ELSE 0 END) AS duplicateCourseAndDepartmentLinks,
    COUNT(DISTINCT official_source_url) AS distinctCourseLinks,
    COUNT(DISTINCT department_source_url) AS distinctDepartmentLinks
  FROM courses
  GROUP BY university_id
  ORDER BY university_id
`).all();

const genericDepartmentLinks = Object.fromEntries(database.prepare(`
  SELECT university_id, department_source_url, COUNT(DISTINCT department) AS departments, COUNT(*) AS courses
  FROM courses
  GROUP BY university_id, department_source_url
  ORDER BY university_id, courses DESC
`).all().reduce((groups, row) => {
  const list = groups.get(row.university_id) ?? [];
  list.push({
    url: row.department_source_url,
    departments: Number(row.departments),
    courses: Number(row.courses),
  });
  groups.set(row.university_id, list);
  return groups;
}, new Map()));

const result = {
  totals: {
    courses: Number(database.prepare('SELECT COUNT(*) AS count FROM courses').get().count),
    cards: Number(database.prepare('SELECT COUNT(*) AS count FROM course_instructors').get().count),
  },
  schools: rows.map((row) => ({
    ...row,
    courses: Number(row.courses),
    departments: Number(row.departments),
    missingCourseLinks: Number(row.missingCourseLinks),
    missingDepartmentLinks: Number(row.missingDepartmentLinks),
    duplicateCourseAndDepartmentLinks: Number(row.duplicateCourseAndDepartmentLinks),
    distinctCourseLinks: Number(row.distinctCourseLinks),
    distinctDepartmentLinks: Number(row.distinctDepartmentLinks),
    mostUsedDepartmentLinks: genericDepartmentLinks[row.universityId].slice(0, 5),
  })),
};

if (process.argv.includes('--write-repair')) {
  const duplicates = database.prepare(`
    SELECT university_id, department, COUNT(DISTINCT department_source_url) AS urls
    FROM courses
    GROUP BY university_id, department
    HAVING urls > 1
  `).all();
  if (duplicates.length) {
    throw new Error(`Cannot create an unambiguous department-link migration: ${JSON.stringify(duplicates)}`);
  }
  const quote = (value) => `'${String(value).replaceAll("'", "''")}'`;
  const links = database.prepare(`
    SELECT university_id, department, MAX(department_source_url) AS url
    FROM courses
    GROUP BY university_id, department
    ORDER BY university_id, department
  `).all();
  const statements = [
    '-- Generated by scripts/audit-course-links.mjs from university-owned public sources only.',
  ];
  for (const row of links) {
    statements.push(`UPDATE courses SET department_source_url = ${quote(row.url)}, updated_at = CURRENT_TIMESTAMP\nWHERE university_id = ${quote(row.university_id)} AND department = ${quote(row.department)};`);
    statements.push(`UPDATE academic_departments SET official_source_url = ${quote(row.url)}, updated_at = CURRENT_TIMESTAMP\nWHERE university_id = ${quote(row.university_id)} AND name = ${quote(row.department)};`);
  }
  statements.push(`INSERT INTO app_runtime_state (key, value, updated_at)\nVALUES ('schema_version', '2026-08-29-course-links-v1', CURRENT_TIMESTAMP)\nON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;`);
  statements.push('PRAGMA optimize;');
  writeFileSync(
    new URL('drizzle/0051_complete_official_course_links.sql', root),
    `${statements.join('\n--> statement-breakpoint\n')}\n`,
    'utf8',
  );
  result.repairMigration = {
    file: '0051_complete_official_course_links.sql',
    departmentMappings: links.length,
  };
}

if (process.argv.includes('--departments')) {
  result.departmentLinks = database.prepare(`
    SELECT university_id AS universityId, department, department_source_url AS url,
      COUNT(*) AS courses
    FROM courses
    GROUP BY university_id, department, department_source_url
    ORDER BY university_id, department, courses DESC
  `).all().map((row) => ({ ...row, courses: Number(row.courses) }));
}

console.log(JSON.stringify(result, null, 2));
database.close();
