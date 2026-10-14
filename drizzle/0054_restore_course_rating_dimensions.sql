ALTER TABLE course_ratings ADD COLUMN learning_score INTEGER CHECK (
  learning_score IS NULL OR (
    typeof(learning_score) = 'integer' AND learning_score BETWEEN 0 AND 100
  )
);
--> statement-breakpoint
ALTER TABLE course_ratings ADD COLUMN grading_standard_score INTEGER CHECK (
  grading_standard_score IS NULL OR (
    typeof(grading_standard_score) = 'integer' AND grading_standard_score BETWEEN 0 AND 100
  )
);
--> statement-breakpoint
UPDATE course_ratings
SET
  learning_score = COALESCE(
    learning_score,
    (SELECT legacy.learning_score * 20
     FROM course_ratings_legacy_1_to_5 AS legacy
     WHERE legacy.id = course_ratings.id)
  ),
  grading_standard_score = COALESCE(
    grading_standard_score,
    (SELECT legacy.grading_standard_score * 20
     FROM course_ratings_legacy_1_to_5 AS legacy
     WHERE legacy.id = course_ratings.id)
  )
WHERE learning_score IS NULL OR grading_standard_score IS NULL;
--> statement-breakpoint
INSERT INTO app_runtime_state (key, value, updated_at)
VALUES ('schema_version', '2026-08-29-course-rating-five-dimensions-v1', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
--> statement-breakpoint
PRAGMA optimize;
