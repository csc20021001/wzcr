CREATE TABLE IF NOT EXISTS app_runtime_state (
  key TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
--> statement-breakpoint
INSERT INTO app_runtime_state (key, value, updated_at)
VALUES ('schema_version', '2026-08-28-v1', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET
  value = excluded.value,
  updated_at = excluded.updated_at;
