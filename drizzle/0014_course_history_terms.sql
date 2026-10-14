ALTER TABLE courses ADD COLUMN first_term TEXT NOT NULL DEFAULT '';
--> statement-breakpoint
ALTER TABLE courses ADD COLUMN last_term TEXT NOT NULL DEFAULT '';
--> statement-breakpoint
ALTER TABLE courses ADD COLUMN offered_terms TEXT NOT NULL DEFAULT '';
--> statement-breakpoint
UPDATE courses
SET first_term = term, last_term = term, offered_terms = term
WHERE first_term = '' OR last_term = '' OR offered_terms = '';
