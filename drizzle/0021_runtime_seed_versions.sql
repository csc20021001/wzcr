CREATE TABLE IF NOT EXISTS app_seed_versions (
  seed_name TEXT PRIMARY KEY NOT NULL,
  version TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
--> statement-breakpoint
INSERT INTO app_seed_versions (seed_name, version, updated_at) VALUES
  ('departments', '2026-08-27-v1', CURRENT_TIMESTAMP),
  ('professors', '2026-08-27-v1', CURRENT_TIMESTAMP),
  ('rentals', '2026-08-27-v2', CURRENT_TIMESTAMP)
ON CONFLICT(seed_name) DO UPDATE SET
  version = excluded.version,
  updated_at = excluded.updated_at;
