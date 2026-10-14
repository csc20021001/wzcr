ALTER TABLE professors ADD COLUMN official_source_url TEXT NOT NULL DEFAULT '';
--> statement-breakpoint
PRAGMA optimize;
