DROP TABLE IF EXISTS rental_comments;
--> statement-breakpoint
DROP TABLE IF EXISTS rental_reports;
--> statement-breakpoint
DROP TABLE IF EXISTS rental_location_universities;
--> statement-breakpoint
DROP TABLE IF EXISTS rental_locations;
--> statement-breakpoint
DROP TABLE IF EXISTS reviews;
--> statement-breakpoint
DROP TABLE IF EXISTS listings;
--> statement-breakpoint
DELETE FROM api_rate_limits
WHERE action LIKE 'rental-%' OR action = 'legacy-listing';
--> statement-breakpoint
DELETE FROM app_seed_versions WHERE seed_name = 'rentals';
--> statement-breakpoint
DELETE FROM universities WHERE id = 'nycu-yangming';
--> statement-breakpoint
INSERT INTO app_runtime_state (key, value, updated_at)
VALUES ('schema_version', '2026-08-29-course-only-v1', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET
  value = excluded.value,
  updated_at = excluded.updated_at;
