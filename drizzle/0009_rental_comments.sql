CREATE TABLE IF NOT EXISTS rental_comments (
  id TEXT PRIMARY KEY NOT NULL,
  rental_location_id TEXT NOT NULL REFERENCES rental_locations(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 4 AND 500),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_rental_comments_location_created
  ON rental_comments(rental_location_id, created_at DESC);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS idx_rental_comments_user_created
  ON rental_comments(user_id, created_at DESC);
--> statement-breakpoint
PRAGMA optimize;
