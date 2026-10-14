INSERT INTO universities
  (id, name, short_name, city, district, latitude, longitude, address, created_at)
VALUES
  ('nycu-yangming', '國立陽明交通大學（陽明校區）', '陽明校區', '臺北市', '北投區',
   25.1196737, 121.5133204, '臺北市北投區立農街二段155號', '2026-08-27T00:00:00.000Z')
ON CONFLICT(id) DO UPDATE SET
  name = excluded.name,
  short_name = excluded.short_name,
  city = excluded.city,
  district = excluded.district,
  latitude = excluded.latitude,
  longitude = excluded.longitude,
  address = excluded.address;
--> statement-breakpoint
INSERT INTO rental_locations (
  id, university_id, address, normalized_address, latitude, longitude, source,
  reference_rent, reference_rent_source, coordinate_source, coordinates_verified,
  created_by_user_id, created_at, updated_at
) VALUES
  ('moe-current-niu-minquan-47-11-4', 'niu', '宜蘭縣宜蘭市民權新路47巷6弄11-4號5樓',
   '宜蘭縣宜蘭市民權新路47巷6弄11之4號5樓', 24.749533, 121.7512315, 'government', 5250,
   '教育部雲端租屋生活網｜https://house.nfu.edu.tw/NIU｜2026-08-21 待租｜刊登租金 NT$4,500–6,000',
   'openstreetmap_street_centroid', 0, NULL, '2026-08-27T03:00:00.000Z', '2026-08-27T03:00:00.000Z'),
  ('moe-current-niu-fuxing-15-10-1', 'niu', '宜蘭縣宜蘭市復興路2段15巷10之1號2樓',
   '宜蘭縣宜蘭市復興路2段15巷10之1號2樓', 24.7481526, 121.749356, 'government', 4250,
   '教育部雲端租屋生活網｜https://house.nfu.edu.tw/NIU｜2026-08-06 待租｜刊登租金 NT$4,000–4,500',
   'openstreetmap_street_centroid', 0, NULL, '2026-08-27T02:00:00.000Z', '2026-08-27T02:00:00.000Z'),
  ('moe-current-niu-nuzhong-71', 'niu', '宜蘭縣宜蘭市女中路3段71號',
   '宜蘭縣宜蘭市女中路3段71號', 24.7449114, 121.7455514, 'government', 4500,
   '教育部雲端租屋生活網｜https://house.nfu.edu.tw/NIU｜2026-07-22 待租｜刊登租金 NT$3,000–6,000',
   'openstreetmap_street_centroid', 0, NULL, '2026-08-27T01:00:00.000Z', '2026-08-27T01:00:00.000Z')
ON CONFLICT(normalized_address) DO UPDATE SET
  university_id = excluded.university_id,
  source = 'government',
  reference_rent = excluded.reference_rent,
  reference_rent_source = excluded.reference_rent_source,
  latitude = excluded.latitude,
  longitude = excluded.longitude,
  coordinate_source = excluded.coordinate_source,
  coordinates_verified = 0,
  created_at = excluded.created_at,
  updated_at = excluded.updated_at;
--> statement-breakpoint
INSERT INTO rental_location_universities (rental_location_id, university_id, created_at)
SELECT id, 'niu', created_at FROM rental_locations
WHERE id IN (
  'moe-current-niu-minquan-47-11-4',
  'moe-current-niu-fuxing-15-10-1',
  'moe-current-niu-nuzhong-71'
)
ON CONFLICT(rental_location_id, university_id) DO NOTHING;
