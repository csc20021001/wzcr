import { getD1 } from './index';

export type DepartmentView = {
  id: string;
  universityId: string;
  college: string;
  name: string;
  unitType: 'department' | 'institute' | 'program' | 'academic-unit';
  officialSourceUrl: string;
};

type DepartmentRow = {
  id: string;
  university_id: string;
  college: string;
  name: string;
  unit_type: DepartmentView['unitType'];
  official_source_url: string;
};

export async function listDepartments(universityId: string) {
  const result = await getD1().prepare(`
    SELECT id, university_id, college, name, unit_type, official_source_url
    FROM academic_departments
    WHERE university_id = ?
    ORDER BY college, name
  `).bind(universityId).all<DepartmentRow>();
  return result.results.map((row) => ({
    id: row.id,
    universityId: row.university_id,
    college: row.college,
    name: row.name,
    unitType: row.unit_type,
    officialSourceUrl: row.official_source_url,
  }));
}
