import { NextResponse } from 'next/server';
import { ensureDatabase, getD1 } from '@/db';

export async function GET() {
  await ensureDatabase();
  const result = await getD1().prepare(`SELECT id, name, short_name, city, district, latitude, longitude, address
    FROM universities ORDER BY rowid`).all<{
      id: string; name: string; short_name: string; city: string; district: string;
      latitude: number; longitude: number; address: string;
    }>();
  const universities = result.results.map((row) => ({
    id: row.id, name: row.name, shortName: row.short_name, city: row.city,
    district: row.district, latitude: Number(row.latitude), longitude: Number(row.longitude), address: row.address,
  }));
  return NextResponse.json({ universities }, {
    headers: { 'Cache-Control': 'public, max-age=300, s-maxage=3600' },
  });
}
