import { getD1 } from './index';
import { maskProfessorName } from '../lib/professor-name.mjs';

export type ProfessorView = {
  id: string;
  universityId: string;
  department: string;
  name: string;
  averageRating: number | null;
  averageAttitude: number | null;
  averageLearning: number | null;
  averageWorkload: number | null;
  averageExamDifficulty: number | null;
  averageGradingStandard: number | null;
  ratingCount: number;
};

type ProfessorRow = {
  id: string;
  university_id: string;
  department: string;
  name: string;
  average_rating: number | null;
  average_attitude: number | null;
  average_learning: number | null;
  average_workload: number | null;
  average_exam_difficulty: number | null;
  average_grading_standard: number | null;
  rating_count: number;
};

const numericOrNull = (value: number | null) => value === null ? null : Number(value);

function mapProfessor(row: ProfessorRow): ProfessorView {
  return {
    id: row.id,
    universityId: row.university_id,
    department: row.department,
    name: maskProfessorName(row.name),
    averageRating: numericOrNull(row.average_rating),
    averageAttitude: numericOrNull(row.average_attitude),
    averageLearning: numericOrNull(row.average_learning),
    averageWorkload: numericOrNull(row.average_workload),
    averageExamDifficulty: numericOrNull(row.average_exam_difficulty),
    averageGradingStandard: numericOrNull(row.average_grading_standard),
    ratingCount: Number(row.rating_count),
  };
}

export async function listProfessors(filters: { universityId?: string; department?: string; search?: string }) {
  const conditions: string[] = [];
  const values: string[] = [];
  if (filters.universityId) {
    conditions.push('p.university_id = ?');
    values.push(filters.universityId);
  }
  if (filters.department) {
    conditions.push('p.department LIKE ?');
    values.push(`%${filters.department}%`);
  }
  if (filters.search) {
    conditions.push('(p.name LIKE ? OR p.department LIKE ?)');
    values.push(`%${filters.search}%`, `%${filters.search}%`);
  }
  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
  const result = await getD1().prepare(`
    SELECT p.id, p.university_id, p.department, p.name,
      ROUND(AVG((pr.attitude_score + pr.learning_score + pr.workload_score + pr.exam_difficulty_score + pr.grading_standard_score) / 5.0), 1) AS average_rating,
      ROUND(AVG(pr.attitude_score), 1) AS average_attitude,
      ROUND(AVG(pr.learning_score), 1) AS average_learning,
      ROUND(AVG(pr.workload_score), 1) AS average_workload,
      ROUND(AVG(pr.exam_difficulty_score), 1) AS average_exam_difficulty,
      ROUND(AVG(pr.grading_standard_score), 1) AS average_grading_standard,
      COUNT(pr.id) AS rating_count
    FROM professors p
    LEFT JOIN professor_ratings pr ON pr.professor_id = p.id
    ${where}
    GROUP BY p.id
    ORDER BY p.university_id, p.department, p.name
    LIMIT 200
  `).bind(...values).all<ProfessorRow>();
  return result.results.map(mapProfessor);
}

export async function getProfessor(id: string) {
  const row = await getD1().prepare(`
    SELECT p.id, p.university_id, p.department, p.name,
      ROUND(AVG((pr.attitude_score + pr.learning_score + pr.workload_score + pr.exam_difficulty_score + pr.grading_standard_score) / 5.0), 1) AS average_rating,
      ROUND(AVG(pr.attitude_score), 1) AS average_attitude,
      ROUND(AVG(pr.learning_score), 1) AS average_learning,
      ROUND(AVG(pr.workload_score), 1) AS average_workload,
      ROUND(AVG(pr.exam_difficulty_score), 1) AS average_exam_difficulty,
      ROUND(AVG(pr.grading_standard_score), 1) AS average_grading_standard,
      COUNT(pr.id) AS rating_count
    FROM professors p
    LEFT JOIN professor_ratings pr ON pr.professor_id = p.id
    WHERE p.id = ?
    GROUP BY p.id
  `).bind(id).first<ProfessorRow>();
  return row ? mapProfessor(row) : null;
}
