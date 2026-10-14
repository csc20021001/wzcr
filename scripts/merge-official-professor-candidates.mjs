import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { departmentSeeds } from '../db/department-seeds.ts';

const seedPath = resolve('db/professors.seed.json');
const candidatePath = resolve('db/professor-candidates.generated.json');
const existing = JSON.parse(readFileSync(seedPath, 'utf8'));
const candidates = JSON.parse(readFileSync(candidatePath, 'utf8'));

const officialDomains = new Map([
  ['ntu', 'ntu.edu.tw'], ['nthu', 'nthu.edu.tw'], ['nycu', 'nycu.edu.tw'],
  ['ncu', 'ncu.edu.tw'], ['nchu', 'nchu.edu.tw'],
  ['ccu', 'ccu.edu.tw'], ['nsysu', 'nsysu.edu.tw'], ['ntust', 'ntust.edu.tw'],
  ['ntut', 'ntut.edu.tw'], ['niu', 'niu.edu.tw'],
]);
const departmentIdentities = new Set(
  departmentSeeds.map((row) => `${row.universityId}\u0000${row.name}`),
);

function identity(row) {
  return `${row.universityId}\u0000${row.department}\u0000${row.name}`;
}

function stableId(row) {
  const digest = createHash('sha256').update(identity(row)).digest('hex').slice(0, 16);
  return `prof-${row.universityId}-${digest}`;
}

function assertOfficial(row) {
  const departmentIdentity = `${row.universityId}\u0000${row.department}`;
  if (!departmentIdentities.has(departmentIdentity)) {
    throw new Error(`Unknown department for ${row.universityId}: ${row.department}`);
  }
  const source = new URL(row.sourceUrl);
  const domain = officialDomains.get(row.universityId);
  if (!domain || source.protocol !== 'https:' ||
      (source.hostname !== domain && !source.hostname.endsWith(`.${domain}`))) {
    throw new Error(`Non-official source for ${row.universityId}/${row.department}/${row.name}`);
  }
}

const byIdentity = new Map();
for (const row of existing) {
  assertOfficial(row);
  byIdentity.set(identity(row), row);
}
for (const candidate of candidates) {
  const row = {
    id: stableId(candidate),
    universityId: candidate.universityId,
    department: candidate.department,
    name: candidate.name,
    sourceUrl: candidate.sourceUrl,
  };
  assertOfficial(row);
  if (!byIdentity.has(identity(row))) byIdentity.set(identity(row), row);
}

const rows = [...byIdentity.values()].sort((left, right) =>
  left.universityId.localeCompare(right.universityId, 'en') ||
  left.department.localeCompare(right.department, 'zh-Hant') ||
  left.name.localeCompare(right.name, 'zh-Hant'));
const ids = new Set(rows.map((row) => row.id));
if (ids.size !== rows.length) throw new Error('Generated professor ids are not unique.');

writeFileSync(seedPath, `${JSON.stringify(rows, null, 2)}\n`);
console.log(`Merged ${existing.length} existing and ${candidates.length} candidate rows into ${rows.length} unique professor seeds.`);
