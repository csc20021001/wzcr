import assert from 'node:assert/strict';
import test from 'node:test';
import { departmentSeeds } from '../db/department-seeds.ts';

const officialDomains = new Map([
  ['ntu', 'ntu.edu.tw'], ['nthu', 'nthu.edu.tw'], ['nycu', 'nycu.edu.tw'],
  ['ncu', 'ncu.edu.tw'], ['nchu', 'nchu.edu.tw'],
  ['ccu', 'ccu.edu.tw'], ['nsysu', 'nsysu.edu.tw'], ['ntust', 'ntust.edu.tw'],
  ['ntut', 'ntut.edu.tw'], ['niu', 'niu.edu.tw'],
]);

test('all supported schools have unique official academic unit seeds', () => {
  assert.ok(departmentSeeds.length >= 650);
  const identities = new Set();
  const counts = new Map();
  for (const row of departmentSeeds) {
    const identity = `${row.universityId}\u0000${row.name}`;
    assert.equal(identities.has(identity), false, `duplicate unit: ${identity}`);
    identities.add(identity);
    counts.set(row.universityId, (counts.get(row.universityId) ?? 0) + 1);
    assert.ok(row.college.length >= 2);
    assert.ok(row.name.length >= 2);
    assert.match(row.id, /^dept-[a-z]+-[0-9a-f]{8}$/);
    const source = new URL(row.sourceUrl);
    const domain = officialDomains.get(row.universityId);
    assert.equal(source.protocol, 'https:');
    assert.ok(domain && (source.hostname === domain || source.hostname.endsWith(`.${domain}`)));
  }
  assert.equal(counts.size, 10);
  for (const schoolId of officialDomains.keys()) assert.ok((counts.get(schoolId) ?? 0) >= 20, schoolId);
});
