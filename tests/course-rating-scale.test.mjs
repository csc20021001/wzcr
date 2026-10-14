import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import {
  isLegacyCourseRatingOneToFiveSchema,
  legacyCourseRatingUpgradeStatements,
} from '../db/course-rating-upgrade.mjs';

const scaleMigration = readFileSync(new URL('../drizzle/0053_course_rating_scale_0_100.sql', import.meta.url), 'utf8')
  .split('--> statement-breakpoint')
  .map((statement) => statement.trim())
  .filter(Boolean);
const restoreDimensionsMigration = readFileSync(new URL('../drizzle/0054_restore_course_rating_dimensions.sql', import.meta.url), 'utf8')
  .split('--> statement-breakpoint')
  .map((statement) => statement.trim())
  .filter(Boolean);

test('0–100 migrations preserve rows and restore the five rating dimensions', () => {
  const database = new DatabaseSync(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE courses (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE course_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      learning_score INTEGER NOT NULL CHECK (learning_score BETWEEN 1 AND 5),
      workload_score INTEGER NOT NULL CHECK (workload_score BETWEEN 1 AND 5),
      exam_difficulty_score INTEGER NOT NULL CHECK (exam_difficulty_score BETWEEN 1 AND 5),
      grading_standard_score INTEGER NOT NULL CHECK (grading_standard_score BETWEEN 1 AND 5),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (user_id, course_id, instructor_name)
    );
    CREATE INDEX idx_course_ratings_course ON course_ratings(course_id, instructor_name);
    CREATE INDEX idx_course_ratings_user ON course_ratings(user_id);
    CREATE UNIQUE INDEX idx_course_ratings_user_course_instructor ON course_ratings(user_id, course_id, instructor_name);
    CREATE TABLE app_runtime_state (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    INSERT INTO users VALUES ('user-1');
    INSERT INTO courses VALUES ('course-1');
    INSERT INTO course_ratings VALUES ('rating-1', 'course-1', '王老師', 'user-1', 1, 2, 3, 5, 'now', 'now');
  `);

  for (const statement of scaleMigration) database.exec(statement);

  const migratedRating = database.prepare(`SELECT workload_score, exam_difficulty_score, attendance_frequency_score
    FROM course_ratings WHERE id = 'rating-1'`).get();
  assert.deepEqual({ ...migratedRating }, {
    workload_score: 40,
    exam_difficulty_score: 60,
    attendance_frequency_score: null,
  });
  const legacyRating = database.prepare(`SELECT learning_score, workload_score, exam_difficulty_score, grading_standard_score
    FROM course_ratings_legacy_1_to_5 WHERE id = 'rating-1'`).get();
  assert.deepEqual({ ...legacyRating }, {
    learning_score: 1,
    workload_score: 2,
    exam_difficulty_score: 3,
    grading_standard_score: 5,
  });

  database.prepare(`INSERT INTO course_ratings (
      id, course_id, instructor_name, user_id, workload_score,
      exam_difficulty_score, attendance_frequency_score, created_at, updated_at
    ) VALUES ('rating-2', 'course-1', '李老師', 'user-1', 0, 100, 73, 'now', 'now')`).run();

  for (const statement of restoreDimensionsMigration) database.exec(statement);

  const restoredLegacyRating = database.prepare(`SELECT learning_score, workload_score,
      exam_difficulty_score, grading_standard_score, attendance_frequency_score
    FROM course_ratings WHERE id = 'rating-1'`).get();
  assert.deepEqual({ ...restoredLegacyRating }, {
    learning_score: 20,
    workload_score: 40,
    exam_difficulty_score: 60,
    grading_standard_score: 100,
    attendance_frequency_score: null,
  });
  const threeDimensionRating = database.prepare(`SELECT learning_score, grading_standard_score,
      attendance_frequency_score FROM course_ratings WHERE id = 'rating-2'`).get();
  assert.deepEqual({ ...threeDimensionRating }, {
    learning_score: null,
    grading_standard_score: null,
    attendance_frequency_score: 73,
  });

  database.prepare(`INSERT INTO course_ratings (
      id, course_id, instructor_name, user_id, learning_score, workload_score,
      exam_difficulty_score, grading_standard_score, attendance_frequency_score, created_at, updated_at
    ) VALUES ('rating-3', 'course-1', '陳老師', 'user-1', 0, 100, 73, 50, 25, 'now', 'now')`).run();
  assert.throws(() => database.prepare(`INSERT INTO course_ratings VALUES
    ('rating-4', 'course-1', '林老師', 'user-1', 50, 50, 50, 'now', 'now', -1, 50)`).run());
  assert.throws(() => database.prepare(`INSERT INTO course_ratings VALUES
    ('rating-5', 'course-1', '張老師', 'user-1', 50, 50, 50, 'now', 'now', 50, 101)`).run());
  assert.throws(() => database.prepare(`INSERT INTO course_ratings VALUES
    ('rating-6', 'course-1', '趙老師', 'user-1', 50.5, 50, 50, 'now', 'now', 50, 50)`).run());
  assert.equal(database.prepare("SELECT value FROM app_runtime_state WHERE key = 'schema_version'").get().value, '2026-08-29-course-rating-five-dimensions-v1');
  database.close();
});

test('runtime fallback safely upgrades the teacher-specific 1–5 table from migration 0024', () => {
  const database = new DatabaseSync(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE users (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE courses (id TEXT PRIMARY KEY NOT NULL);
    CREATE TABLE course_ratings (
      id TEXT PRIMARY KEY NOT NULL,
      course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
      instructor_name TEXT NOT NULL,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      learning_score INTEGER NOT NULL CHECK (learning_score BETWEEN 1 AND 5),
      workload_score INTEGER NOT NULL CHECK (workload_score BETWEEN 1 AND 5),
      exam_difficulty_score INTEGER NOT NULL CHECK (exam_difficulty_score BETWEEN 1 AND 5),
      grading_standard_score INTEGER NOT NULL CHECK (grading_standard_score BETWEEN 1 AND 5),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (user_id, course_id, instructor_name)
    );
    CREATE INDEX idx_course_ratings_course ON course_ratings(course_id, instructor_name);
    CREATE INDEX idx_course_ratings_user ON course_ratings(user_id);
    CREATE UNIQUE INDEX idx_course_ratings_user_course_instructor
      ON course_ratings(user_id, course_id, instructor_name);
    INSERT INTO users VALUES ('user-1'), ('user-2');
    INSERT INTO courses VALUES ('course-1');
    INSERT INTO course_ratings VALUES
      ('rating-1', 'course-1', '王老師', 'user-1', 1, 2, 3, 4, 'created-1', 'updated-1'),
      ('rating-2', 'course-1', '李老師', 'user-2', 5, 4, 2, 1, 'created-2', 'updated-2');
  `);

  const columns = database.prepare('PRAGMA table_info(course_ratings)').all().map((column) => column.name);
  const createSql = database.prepare(`SELECT sql FROM sqlite_master
    WHERE type = 'table' AND name = 'course_ratings'`).get().sql;
  assert.equal(isLegacyCourseRatingOneToFiveSchema(columns, createSql), true);

  database.exec('BEGIN');
  try {
    for (const statement of legacyCourseRatingUpgradeStatements) database.exec(statement);
    database.exec('COMMIT');
  } catch (error) {
    database.exec('ROLLBACK');
    throw error;
  }

  assert.deepEqual(database.prepare(`SELECT id, course_id, instructor_name, user_id,
      learning_score, workload_score, exam_difficulty_score, grading_standard_score,
      attendance_frequency_score, created_at, updated_at
    FROM course_ratings ORDER BY id`).all().map((row) => ({ ...row })), [
    {
      id: 'rating-1', course_id: 'course-1', instructor_name: '王老師', user_id: 'user-1',
      learning_score: 20, workload_score: 40, exam_difficulty_score: 60,
      grading_standard_score: 80, attendance_frequency_score: null,
      created_at: 'created-1', updated_at: 'updated-1',
    },
    {
      id: 'rating-2', course_id: 'course-1', instructor_name: '李老師', user_id: 'user-2',
      learning_score: 100, workload_score: 80, exam_difficulty_score: 40,
      grading_standard_score: 20, attendance_frequency_score: null,
      created_at: 'created-2', updated_at: 'updated-2',
    },
  ]);
  assert.deepEqual({ ...database.prepare(`SELECT learning_score, workload_score,
      exam_difficulty_score, grading_standard_score FROM course_ratings_legacy_1_to_5
    WHERE id = 'rating-1'`).get() }, {
    learning_score: 1,
    workload_score: 2,
    exam_difficulty_score: 3,
    grading_standard_score: 4,
  });
  database.prepare(`INSERT INTO course_ratings (
    id, course_id, instructor_name, user_id, learning_score, workload_score,
    exam_difficulty_score, grading_standard_score, attendance_frequency_score, created_at, updated_at
  ) VALUES ('rating-3', 'course-1', '林老師', 'user-1', 0, 100, 73, 50, 25, 'now', 'now')`).run();
  assert.deepEqual({ ...database.prepare(`SELECT learning_score, workload_score,
      exam_difficulty_score, grading_standard_score, attendance_frequency_score
    FROM course_ratings WHERE id = 'rating-3'`).get() }, {
    learning_score: 0,
    workload_score: 100,
    exam_difficulty_score: 73,
    grading_standard_score: 50,
    attendance_frequency_score: 25,
  });
  assert.throws(() => database.prepare(`INSERT INTO course_ratings (
    id, course_id, instructor_name, user_id, learning_score, workload_score,
    exam_difficulty_score, grading_standard_score, attendance_frequency_score, created_at, updated_at
  ) VALUES ('invalid', 'course-1', '陳老師', 'user-1', -1, 50, 50, 50, 50, 'now', 'now')`).run());
  assert.equal(isLegacyCourseRatingOneToFiveSchema(
    ['instructor_name', 'learning_score', 'workload_score', 'exam_difficulty_score', 'grading_standard_score'],
    `CREATE TABLE course_ratings (
      learning_score INTEGER CHECK (learning_score BETWEEN 0 AND 100),
      workload_score INTEGER CHECK (workload_score BETWEEN 0 AND 100),
      exam_difficulty_score INTEGER CHECK (exam_difficulty_score BETWEEN 0 AND 100),
      grading_standard_score INTEGER CHECK (grading_standard_score BETWEEN 0 AND 100)
    )`,
  ), false);
  assert.equal(isLegacyCourseRatingOneToFiveSchema(
    database.prepare('PRAGMA table_info(course_ratings)').all().map((column) => column.name),
    database.prepare(`SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'course_ratings'`).get().sql,
  ), false);
  database.close();
});

test('course interface presents five editable 0–100 controls without a combined score', () => {
  const source = readFileSync(new URL('../app/courses/course-directory.tsx', import.meta.url), 'utf8');
  assert.match(source, /min="0" max="100" step="1"/);
  assert.match(source, /0–100 分課程評分/);
  assert.match(source, /label: '學習收穫'/);
  assert.match(source, /label: '作業量'/);
  assert.match(source, /label: '考試難度'/);
  assert.match(source, /label: '給分標準'/);
  assert.match(source, /label: '點名頻率'/);
  assert.match(source, /送出五項課程評分/);
  assert.doesNotMatch(source, /averageRating|綜合分數|綜合平均/);
  assert.doesNotMatch(source, /\[1, 2, 3, 4, 5\]/);
});

test('rating directions stay complete but detailed guidance is collapsed by default', () => {
  const source = readFileSync(new URL('../app/courses/course-directory.tsx', import.meta.url), 'utf8');
  const readme = readFileSync(new URL('../README.md', import.meta.url), 'utf8');
  const dimensions = [
    { label: '學習收穫', hint: '越高代表越能學到東西', meaning: '這門課帶來的知識與能力收穫越紮實', polarity: 'benefit' },
    { label: '作業量', hint: '越高代表作業越多', meaning: '作業與報告越多、越花時間', polarity: 'intensity' },
    { label: '考試難度', hint: '越高代表考試越難', meaning: '考試越難、越不容易拿分', polarity: 'intensity' },
    { label: '給分標準', hint: '越高代表給分越寬鬆', meaning: '老師給分越寬鬆（越甜）', polarity: 'benefit' },
    { label: '點名頻率', hint: '越高代表越常點名', meaning: '越常點名、缺席越容易被記錄', polarity: 'intensity' },
  ];
  for (const dimension of dimensions) {
    assert.ok(source.includes(`hint: '${dimension.hint}'`), `${dimension.label} 缺少欄位短提示`);
    assert.ok(source.includes(`分數越高，代表${dimension.meaning}`), `${dimension.label} 缺少高分方向說明`);
    assert.ok(source.includes(`polarity: '${dimension.polarity}'`), `${dimension.label} 缺少方向標記`);
    assert.ok(readme.includes(dimension.meaning), `README 缺少 ${dimension.label} 的高分說明`);
  }
  const ratingFormStart = source.indexOf('{ratingDimensions.map((dimension) => <fieldset');
  const ratingFormEnd = source.indexOf('</form>', ratingFormStart);
  assert.ok(ratingFormStart >= 0 && ratingFormEnd > ratingFormStart);
  assert.match(
    source.slice(ratingFormStart, ratingFormEnd),
    /<legend>\{dimension\.label\}<small>\{dimension\.hint\}<\/small><\/legend>/,
  );
  assert.match(source, /五項評分越高代表什麼/);
  assert.match(source, /<details className="rating-legend">/);
  assert.match(source, /<summary>/);
  assert.match(source, /rating-legend-open-label">查看詳情/);
  assert.match(source, /rating-legend-close-label">收起詳情/);
  assert.doesNotMatch(source, /<details className="rating-legend"[^>]*\sopen(?:\s|=|>)/);
  const legendStart = source.indexOf('<details className="rating-legend">');
  const summaryEnd = source.indexOf('</summary>', legendStart);
  const detailsEnd = source.indexOf('</details>', summaryEnd);
  assert.ok(legendStart >= 0 && summaryEnd > legendStart && detailsEnd > summaryEnd);
  assert.ok(source.indexOf('<dl>', summaryEnd) < detailsEnd, '詳細說明必須收在 disclosure 內');
  assert.match(source, /dimension-meaning/);
  assert.match(source, /高分不等於好課/);
  assert.match(readme, /## 五項評分越高代表什麼/);
});
