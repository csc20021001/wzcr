-- Remove every 成大 record before deleting the university itself.
DELETE FROM reviews WHERE listing_id IN (SELECT id FROM listings WHERE university_id = 'ncku');
--> statement-breakpoint
DELETE FROM listings WHERE university_id = 'ncku';
--> statement-breakpoint
DELETE FROM rental_comments WHERE rental_location_id IN (SELECT id FROM rental_locations WHERE university_id = 'ncku');
--> statement-breakpoint
DELETE FROM rental_reports WHERE rental_location_id IN (SELECT id FROM rental_locations WHERE university_id = 'ncku');
--> statement-breakpoint
DELETE FROM rental_location_universities WHERE university_id = 'ncku';
--> statement-breakpoint
DELETE FROM rental_locations WHERE university_id = 'ncku';
--> statement-breakpoint
DELETE FROM course_ratings WHERE course_id IN (SELECT id FROM courses WHERE university_id = 'ncku');
--> statement-breakpoint
DELETE FROM course_instructors WHERE course_id IN (SELECT id FROM courses WHERE university_id = 'ncku');
--> statement-breakpoint
DELETE FROM courses WHERE university_id = 'ncku';
--> statement-breakpoint
DELETE FROM professor_ratings WHERE professor_id IN (SELECT id FROM professors WHERE university_id = 'ncku');
--> statement-breakpoint
DELETE FROM professors WHERE university_id = 'ncku';
--> statement-breakpoint
DELETE FROM academic_departments WHERE university_id = 'ncku';
--> statement-breakpoint
DELETE FROM universities WHERE id = 'ncku';
--> statement-breakpoint

INSERT INTO universities (id, name, short_name, city, district, latitude, longitude, address, created_at) VALUES
  ('cycu', '中原大學', '中原', '桃園市', '中壢區', 24.9576, 121.2407, '桃園市中壢區中北路200號', CURRENT_TIMESTAMP),
  ('tku', '淡江大學', '淡江', '新北市', '淡水區', 25.1754, 121.4500, '新北市淡水區英專路151號', CURRENT_TIMESTAMP),
  ('yzu', '元智大學', '元智', '桃園市', '中壢區', 24.9704, 121.2635, '桃園市中壢區遠東路135號', CURRENT_TIMESTAMP),
  ('fcu', '逢甲大學', '逢甲', '臺中市', '西屯區', 24.1788, 120.6466, '臺中市西屯區文華路100號', CURRENT_TIMESTAMP)
ON CONFLICT(id) DO UPDATE SET
  name = excluded.name,
  short_name = excluded.short_name,
  city = excluded.city,
  district = excluded.district,
  latitude = excluded.latitude,
  longitude = excluded.longitude,
  address = excluded.address;
--> statement-breakpoint

UPDATE app_runtime_state
SET value = '2026-08-28-v2', updated_at = CURRENT_TIMESTAMP
WHERE key = 'schema_version';

