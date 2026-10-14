ALTER TABLE universities ADD COLUMN created_at TEXT;
--> statement-breakpoint
CREATE TABLE professors (
  id TEXT PRIMARY KEY NOT NULL,
  university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  department TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX idx_professors_identity ON professors(university_id, department, name);
--> statement-breakpoint
CREATE INDEX idx_professors_university ON professors(university_id);
--> statement-breakpoint
CREATE INDEX idx_professors_department ON professors(department);
--> statement-breakpoint
CREATE INDEX idx_professors_name ON professors(name);
--> statement-breakpoint
CREATE TABLE professor_ratings (
  id TEXT PRIMARY KEY NOT NULL,
  professor_id TEXT NOT NULL REFERENCES professors(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  easy_to_pass_score INTEGER NOT NULL CHECK (easy_to_pass_score BETWEEN 1 AND 5),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX idx_professor_ratings_user_professor ON professor_ratings(user_id, professor_id);
--> statement-breakpoint
CREATE INDEX idx_professor_ratings_professor ON professor_ratings(professor_id);
--> statement-breakpoint
CREATE INDEX idx_professor_ratings_user ON professor_ratings(user_id);
--> statement-breakpoint
CREATE TABLE rental_locations (
  id TEXT PRIMARY KEY NOT NULL,
  university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE RESTRICT,
  address TEXT NOT NULL,
  normalized_address TEXT NOT NULL,
  latitude REAL,
  longitude REAL,
  source TEXT NOT NULL CHECK (source IN ('government', 'user', 'admin')),
  reference_rent INTEGER CHECK (reference_rent IS NULL OR reference_rent > 0),
  reference_rent_source TEXT,
  coordinate_source TEXT,
  coordinates_verified INTEGER NOT NULL DEFAULT 0 CHECK (coordinates_verified IN (0, 1)),
  created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK ((latitude IS NULL AND longitude IS NULL) OR
         (latitude BETWEEN 21.8 AND 25.5 AND longitude BETWEEN 119.3 AND 122.1))
);
--> statement-breakpoint
CREATE UNIQUE INDEX idx_rental_locations_normalized_address ON rental_locations(normalized_address);
--> statement-breakpoint
CREATE INDEX idx_rental_locations_university ON rental_locations(university_id);
--> statement-breakpoint
CREATE INDEX idx_rental_locations_coordinates ON rental_locations(latitude, longitude);
--> statement-breakpoint
CREATE TABLE rental_location_universities (
  rental_location_id TEXT NOT NULL REFERENCES rental_locations(id) ON DELETE CASCADE,
  university_id TEXT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (rental_location_id, university_id)
);
--> statement-breakpoint
CREATE INDEX idx_rental_location_universities_university ON rental_location_universities(university_id, rental_location_id);
--> statement-breakpoint
CREATE TABLE rental_reports (
  id TEXT PRIMARY KEY NOT NULL,
  rental_location_id TEXT NOT NULL REFERENCES rental_locations(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  monthly_rent INTEGER NOT NULL CHECK (monthly_rent BETWEEN 1000 AND 200000),
  overall_rating INTEGER NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
  is_valid INTEGER NOT NULL DEFAULT 1 CHECK (is_valid IN (0, 1)),
  is_outlier INTEGER NOT NULL DEFAULT 0 CHECK (is_outlier IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX idx_rental_reports_user_location ON rental_reports(user_id, rental_location_id);
--> statement-breakpoint
CREATE INDEX idx_rental_reports_location ON rental_reports(rental_location_id);
--> statement-breakpoint
CREATE INDEX idx_rental_reports_user ON rental_reports(user_id);
--> statement-breakpoint
CREATE INDEX idx_rental_reports_aggregate ON rental_reports(rental_location_id, is_valid, is_outlier);
--> statement-breakpoint
CREATE TABLE api_rate_limits (
  user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  window_started_at INTEGER NOT NULL,
  request_count INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, action, window_started_at)
);
--> statement-breakpoint
CREATE INDEX idx_api_rate_limits_cleanup ON api_rate_limits(window_started_at);
--> statement-breakpoint
PRAGMA optimize;
