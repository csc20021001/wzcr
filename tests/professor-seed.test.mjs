import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import { departmentSeeds } from '../db/department-seeds.ts';
import { professorSeeds } from '../db/professors-seeds.generated.ts';

const seeds = JSON.parse(
  readFileSync(new URL('../db/professors.seed.json', import.meta.url), 'utf8'),
);
const generatedSql = readFileSync(
  new URL('../db/professors-seed.generated.sql', import.meta.url),
  'utf8',
);

const officialDomains = {
  ntu: 'ntu.edu.tw',
  nthu: 'nthu.edu.tw',
  nycu: 'nycu.edu.tw',
  ncu: 'ncu.edu.tw',
  nchu: 'nchu.edu.tw',
  ccu: 'ccu.edu.tw',
  nsysu: 'nsysu.edu.tw',
  ntust: 'ntust.edu.tw',
  ntut: 'ntut.edu.tw',
  niu: 'niu.edu.tw',
};

const supportedUniversities = Object.keys(officialDomains);
const departmentIdentities = new Set(
  departmentSeeds.map((row) => `${row.universityId}\u0000${row.name}`),
);

test('professor seed contains only unique official university records', () => {
  assert.ok(seeds.length >= 2400, 'official professor coverage must remain above 2,400 records');
  assert.equal(new Set(seeds.map((row) => row.id)).size, seeds.length);
  assert.equal(
    new Set(seeds.map((row) => `${row.universityId}\u0000${row.department}\u0000${row.name}`)).size,
    seeds.length,
  );

  for (const universityId of supportedUniversities) {
    assert.ok(
      seeds.some((row) => row.universityId === universityId),
      `${universityId} must include at least one official professor record`,
    );
  }

  for (const row of seeds) {
    const source = new URL(row.sourceUrl);
    const expectedDomain = officialDomains[row.universityId];
    assert.equal(source.protocol, 'https:');
    assert.equal(
      source.hostname === expectedDomain || source.hostname.endsWith(`.${expectedDomain}`),
      true,
      `${row.id} must use the official ${expectedDomain} domain`,
    );
    assert.doesNotMatch(source.hostname, /forum|dcard|ptt/i);
    assert.ok(
      departmentIdentities.has(`${row.universityId}\u0000${row.department}`),
      `${row.universityId}/${row.department} must exist in the academic unit directory`,
    );
  }
});

test('generated professor seeds unify one person across departments', () => {
  assert.equal(
    new Set(professorSeeds.map((row) => `${row.universityId}\u0000${row.name}`)).size,
    professorSeeds.length,
  );
  assert.ok(professorSeeds.some((row) => row.department.includes('／')));
  for (const row of professorSeeds) {
    for (const department of row.department.split('／')) {
      assert.ok(
        departmentIdentities.has(`${row.universityId}\u0000${department}`),
        `${row.universityId}/${department} must exist in the academic unit directory`,
      );
    }
  }
});

test('generated professor SQL imports all official-source records', () => {
  const database = new DatabaseSync(':memory:');
  database.exec(`
    PRAGMA foreign_keys = ON;
    CREATE TABLE universities (id TEXT PRIMARY KEY NOT NULL);
    INSERT INTO universities (id) VALUES
      ('ntu'), ('nthu'), ('nycu'), ('ncu'), ('nchu'),
      ('nsysu'), ('ccu'), ('ntust'), ('ntut'), ('niu');
    CREATE TABLE professors (
      id TEXT PRIMARY KEY NOT NULL,
      university_id TEXT NOT NULL REFERENCES universities(id),
      department TEXT NOT NULL,
      name TEXT NOT NULL,
      official_source_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (university_id, name)
    );
  `);
  database.exec(generatedSql);

  assert.equal(database.prepare('SELECT COUNT(*) AS count FROM professors').get().count, professorSeeds.length);
  assert.equal(
    database.prepare("SELECT COUNT(*) AS count FROM professors WHERE official_source_url = ''").get().count,
    0,
  );
  assert.deepEqual(
    database.prepare('SELECT DISTINCT university_id FROM professors ORDER BY university_id').all()
      .map((row) => row.university_id),
    [...supportedUniversities].sort(),
  );
});
