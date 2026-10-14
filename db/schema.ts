import { sql } from 'drizzle-orm';
import { check, index, integer, primaryKey, real, sqliteTable, text, uniqueIndex } from 'drizzle-orm/sqlite-core';

export const universities = sqliteTable('universities', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  shortName: text('short_name').notNull(),
  city: text('city').notNull(),
  district: text('district').notNull(),
  latitude: real('latitude').notNull(),
  longitude: real('longitude').notNull(),
  address: text('address').notNull(),
  createdAt: text('created_at'),
});

export const users = sqliteTable('users', {
  id: text('id').primaryKey(),
  googleSub: text('google_sub').notNull(),
  email: text('email').notNull(),
  name: text('name').notNull(),
  avatarUrl: text('avatar_url'),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  uniqueIndex('idx_users_google_sub').on(table.googleSub),
  index('idx_users_email').on(table.email),
]);

export const authSessions = sqliteTable('auth_sessions', {
  id: text('id').primaryKey(),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  expiresAt: text('expires_at').notNull(),
  createdAt: text('created_at').notNull(),
}, (table) => [
  index('idx_auth_sessions_user_expires').on(table.userId, table.expiresAt),
]);

export const academicDepartments = sqliteTable('academic_departments', {
  id: text('id').primaryKey(),
  universityId: text('university_id').notNull().references(() => universities.id, { onDelete: 'cascade' }),
  college: text('college').notNull(),
  name: text('name').notNull(),
  unitType: text('unit_type').notNull(),
  officialSourceUrl: text('official_source_url').notNull(),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  index('idx_academic_departments_university_college').on(table.universityId, table.college, table.name),
  index('idx_academic_departments_name').on(table.name),
  uniqueIndex('idx_academic_departments_identity').on(table.universityId, table.name),
]);

export const professors = sqliteTable('professors', {
  id: text('id').primaryKey(),
  universityId: text('university_id').notNull().references(() => universities.id, { onDelete: 'cascade' }),
  department: text('department').notNull(),
  name: text('name').notNull(),
  officialSourceUrl: text('official_source_url').notNull().default(''),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  index('idx_professors_university').on(table.universityId),
  index('idx_professors_department').on(table.department),
  index('idx_professors_name').on(table.name),
  uniqueIndex('idx_professors_identity').on(table.universityId, table.name),
]);

export const professorRatings = sqliteTable('professor_ratings', {
  id: text('id').primaryKey(),
  professorId: text('professor_id').notNull().references(() => professors.id, { onDelete: 'cascade' }),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  easyToPassScore: integer('easy_to_pass_score').notNull(),
  attitudeScore: integer('attitude_score').notNull().default(3),
  learningScore: integer('learning_score').notNull().default(3),
  workloadScore: integer('workload_score').notNull().default(3),
  examDifficultyScore: integer('exam_difficulty_score').notNull().default(3),
  gradingStandardScore: integer('grading_standard_score').notNull().default(3),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  index('idx_professor_ratings_professor').on(table.professorId),
  index('idx_professor_ratings_user').on(table.userId),
  uniqueIndex('idx_professor_ratings_user_professor').on(table.userId, table.professorId),
]);

export const courses = sqliteTable('courses', {
  id: text('id').primaryKey(),
  universityId: text('university_id').notNull().references(() => universities.id, { onDelete: 'cascade' }),
  term: text('term').notNull(),
  firstTerm: text('first_term').notNull().default(''),
  lastTerm: text('last_term').notNull().default(''),
  offeredTerms: text('offered_terms').notNull().default(''),
  semester: text('semester').notNull().default(''),
  courseCode: text('course_code').notNull(),
  name: text('name').notNull(),
  department: text('department').notNull(),
  officialSourceUrl: text('official_source_url').notNull(),
  departmentSourceUrl: text('department_source_url').notNull().default(''),
  sourceType: text('source_type').notNull().default('official'),
  submittedByUserId: text('submitted_by_user_id'),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  index('idx_courses_university_term').on(table.universityId, table.term, table.department, table.name),
  index('idx_courses_name').on(table.name),
  index('idx_courses_department').on(table.department),
  uniqueIndex('idx_courses_identity').on(table.universityId, table.term, table.courseCode),
]);

export const courseInstructors = sqliteTable('course_instructors', {
  courseId: text('course_id').notNull().references(() => courses.id, { onDelete: 'cascade' }),
  instructorName: text('instructor_name').notNull(),
  professorId: text('professor_id').references(() => professors.id, { onDelete: 'set null' }),
  officialSourceUrl: text('official_source_url').notNull().default(''),
  createdAt: text('created_at').notNull(),
}, (table) => [
  primaryKey({ columns: [table.courseId, table.instructorName] }),
  index('idx_course_instructors_name').on(table.instructorName),
  index('idx_course_instructors_professor').on(table.professorId),
]);

export const courseRatings = sqliteTable('course_ratings', {
  id: text('id').primaryKey(),
  courseId: text('course_id').notNull().references(() => courses.id, { onDelete: 'cascade' }),
  instructorName: text('instructor_name').notNull(),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  learningScore: integer('learning_score'),
  workloadScore: integer('workload_score').notNull(),
  examDifficultyScore: integer('exam_difficulty_score').notNull(),
  gradingStandardScore: integer('grading_standard_score'),
  attendanceFrequencyScore: integer('attendance_frequency_score'),
  createdAt: text('created_at').notNull(),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  check('course_ratings_learning_score_range', sql`${table.learningScore} IS NULL OR (typeof(${table.learningScore}) = 'integer' AND ${table.learningScore} BETWEEN 0 AND 100)`),
  check('course_ratings_workload_score_range', sql`typeof(${table.workloadScore}) = 'integer' AND ${table.workloadScore} BETWEEN 0 AND 100`),
  check('course_ratings_exam_difficulty_score_range', sql`typeof(${table.examDifficultyScore}) = 'integer' AND ${table.examDifficultyScore} BETWEEN 0 AND 100`),
  check('course_ratings_grading_standard_score_range', sql`${table.gradingStandardScore} IS NULL OR (typeof(${table.gradingStandardScore}) = 'integer' AND ${table.gradingStandardScore} BETWEEN 0 AND 100)`),
  check('course_ratings_attendance_frequency_score_range', sql`${table.attendanceFrequencyScore} IS NULL OR (typeof(${table.attendanceFrequencyScore}) = 'integer' AND ${table.attendanceFrequencyScore} BETWEEN 0 AND 100)`),
  index('idx_course_ratings_course').on(table.courseId),
  index('idx_course_ratings_user').on(table.userId),
  uniqueIndex('idx_course_ratings_user_course_instructor').on(table.userId, table.courseId, table.instructorName),
]);

export const apiRateLimits = sqliteTable('api_rate_limits', {
  userId: text('user_id').notNull(),
  action: text('action').notNull(),
  windowStartedAt: integer('window_started_at').notNull(),
  requestCount: integer('request_count').notNull().default(1),
  updatedAt: text('updated_at').notNull(),
}, (table) => [
  primaryKey({ columns: [table.userId, table.action, table.windowStartedAt] }),
  index('idx_api_rate_limits_cleanup').on(table.windowStartedAt),
]);
