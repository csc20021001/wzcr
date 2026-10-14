CREATE TABLE IF NOT EXISTS _professor_identity_map (
  old_id TEXT PRIMARY KEY NOT NULL,
  canonical_id TEXT NOT NULL,
  merged_department TEXT NOT NULL
);
--> statement-breakpoint
DELETE FROM _professor_identity_map;
--> statement-breakpoint
INSERT INTO _professor_identity_map (old_id, canonical_id, merged_department)
SELECT p.id, grouped.canonical_id, grouped.merged_department
FROM professors p
JOIN (
  SELECT university_id, name, MIN(id) AS canonical_id,
    REPLACE(GROUP_CONCAT(DISTINCT department), ',', '／') AS merged_department
  FROM professors
  GROUP BY university_id, name
) grouped ON grouped.university_id = p.university_id AND grouped.name = p.name;
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS _professor_rating_rank (
  rating_id TEXT PRIMARY KEY NOT NULL,
  canonical_id TEXT NOT NULL,
  identity_rank INTEGER NOT NULL
);
--> statement-breakpoint
DELETE FROM _professor_rating_rank;
--> statement-breakpoint
INSERT INTO _professor_rating_rank (rating_id, canonical_id, identity_rank)
SELECT pr.id, identity_map.canonical_id,
  ROW_NUMBER() OVER (
    PARTITION BY pr.user_id, identity_map.canonical_id
    ORDER BY pr.updated_at DESC, pr.id DESC
  ) AS identity_rank
FROM professor_ratings pr
JOIN _professor_identity_map identity_map ON identity_map.old_id = pr.professor_id;
--> statement-breakpoint
DELETE FROM professor_ratings
WHERE id IN (SELECT rating_id FROM _professor_rating_rank WHERE identity_rank > 1);
--> statement-breakpoint
UPDATE professor_ratings
SET professor_id = (
  SELECT canonical_id FROM _professor_rating_rank WHERE rating_id = professor_ratings.id
)
WHERE id IN (SELECT rating_id FROM _professor_rating_rank WHERE identity_rank = 1);
--> statement-breakpoint
DELETE FROM professors
WHERE id IN (
  SELECT old_id FROM _professor_identity_map WHERE old_id != canonical_id
);
--> statement-breakpoint
UPDATE professors
SET department = (
  SELECT merged_department FROM _professor_identity_map
  WHERE canonical_id = professors.id LIMIT 1
), updated_at = CURRENT_TIMESTAMP
WHERE id IN (SELECT canonical_id FROM _professor_identity_map);
--> statement-breakpoint
DROP INDEX IF EXISTS idx_professors_identity;
--> statement-breakpoint
CREATE UNIQUE INDEX idx_professors_identity ON professors(university_id, name);
--> statement-breakpoint
DROP TABLE _professor_rating_rank;
--> statement-breakpoint
DROP TABLE _professor_identity_map;
