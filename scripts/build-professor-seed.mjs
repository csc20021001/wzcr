import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const sourcePath = resolve('db/professors.seed.json');
const outputPath = resolve('db/professors-seed.generated.sql');
const typescriptOutputPath = resolve('db/professors-seeds.generated.ts');
const allowedUniversities = new Set(['ntu', 'nthu', 'nycu', 'ncu', 'nchu', 'nsysu', 'ccu', 'ntust', 'ntut', 'niu']);
const officialDomains = new Map([
  ['ntu', 'ntu.edu.tw'], ['nthu', 'nthu.edu.tw'], ['nycu', 'nycu.edu.tw'],
  ['ncu', 'ncu.edu.tw'], ['nchu', 'nchu.edu.tw'],
  ['nsysu', 'nsysu.edu.tw'], ['ccu', 'ccu.edu.tw'], ['ntust', 'ntust.edu.tw'],
  ['ntut', 'ntut.edu.tw'], ['niu', 'niu.edu.tw'],
]);
const rawRows = JSON.parse(readFileSync(sourcePath, 'utf8'));
if (!Array.isArray(rawRows)) throw new Error('db/professors.seed.json 必須是陣列。');

const seenIds = new Set();
const seenSourceIdentities = new Set();
const sqlString = (value) => `'${String(value).replaceAll("'", "''")}'`;
const verifiedRows = rawRows.map((row, index) => {
  const id = String(row.id ?? '').trim();
  const universityId = String(row.universityId ?? '').trim();
  const department = String(row.department ?? '').trim();
  const name = String(row.name ?? '').trim();
  const sourceUrl = String(row.sourceUrl ?? '').trim();
  if (!/^[a-z0-9-]{2,80}$/i.test(id)) throw new Error(`第 ${index + 1} 筆教授 id 格式不正確。`);
  if (!allowedUniversities.has(universityId)) throw new Error(`第 ${index + 1} 筆 universityId 不在支援名單。`);
  if (department.length < 2 || department.length > 80 || name.length < 2 || name.length > 40) {
    throw new Error(`第 ${index + 1} 筆教授姓名或系所長度不正確。`);
  }
  let parsedSource;
  try {
    parsedSource = new URL(sourceUrl);
  } catch {
    throw new Error(`第 ${index + 1} 筆官方來源網址格式不正確。`);
  }
  const officialDomain = officialDomains.get(universityId);
  if (parsedSource.protocol !== 'https:' || !officialDomain ||
    (parsedSource.hostname !== officialDomain && !parsedSource.hostname.endsWith(`.${officialDomain}`))) {
    throw new Error(`第 ${index + 1} 筆來源不是該校官方 HTTPS 網域。`);
  }
  if (seenIds.has(id)) throw new Error(`第 ${index + 1} 筆教授 id 重複。`);
  seenIds.add(id);
  const sourceIdentity = `${universityId}\u0000${department}\u0000${name}`;
  if (seenSourceIdentities.has(sourceIdentity)) throw new Error(`第 ${index + 1} 筆教授資料重複。`);
  seenSourceIdentities.add(sourceIdentity);
  return { id, universityId, department, name, sourceUrl };
});

const grouped = new Map();
for (const row of verifiedRows) {
  const identity = `${row.universityId}\u0000${row.name}`;
  const current = grouped.get(identity);
  if (!current) {
    grouped.set(identity, { ...row, departments: new Set([row.department]) });
    continue;
  }
  current.departments.add(row.department);
  if (row.id.localeCompare(current.id) < 0) {
    current.id = row.id;
    current.sourceUrl = row.sourceUrl;
  }
}

const rows = [...grouped.values()].map(({ departments, ...row }) => ({
  ...row,
  department: [...departments].sort((a, b) => a.localeCompare(b, 'zh-Hant')).join('／'),
})).sort((a, b) => `${a.universityId}\u0000${a.name}`.localeCompare(`${b.universityId}\u0000${b.name}`, 'zh-Hant'));

const statements = rows.map((row) => {
  const { id, universityId, department, name, sourceUrl } = row;
  return `INSERT INTO professors (id, university_id, department, name, official_source_url, created_at, updated_at)
VALUES (${sqlString(id)}, ${sqlString(universityId)}, ${sqlString(department)}, ${sqlString(name)}, ${sqlString(sourceUrl)}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT(university_id, name) DO UPDATE SET department = excluded.department, official_source_url = excluded.official_source_url, updated_at = CURRENT_TIMESTAMP;`;
});

writeFileSync(outputPath, `${statements.join('\n--> statement-breakpoint\n')}${statements.length ? '\n--> statement-breakpoint\n' : ''}PRAGMA optimize;\n`);
writeFileSync(typescriptOutputPath, `export type ProfessorSeed = {\n  id: string;\n  universityId: string;\n  department: string;\n  name: string;\n  sourceUrl: string;\n};\n\nexport const professorSeeds: ProfessorSeed[] = ${JSON.stringify(rows, null, 2)};\n`);
console.log(`Wrote ${rows.length} professor seed row(s) to SQL and TypeScript outputs.`);
