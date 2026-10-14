ALTER TABLE professor_ratings ADD COLUMN learning_score INTEGER NOT NULL DEFAULT 3
  CHECK (learning_score BETWEEN 1 AND 5);
--> statement-breakpoint
PRAGMA optimize;
