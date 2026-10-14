import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const inputPath = resolve('tmp/pdfs/nycu-website-health-list.txt');
const outputPath = resolve('db/nycu-official-units.generated.json');

function normalize(value) {
  return value
    .normalize('NFKC')
    .replaceAll('台', '臺')
    .replace(/[（(].*?[）)]/g, '')
    .replace(/[\s\-—–_、，,。．・·/​]/g, '')
    .toLowerCase();
}

const text = readFileSync(inputPath, 'utf8');
const entries = [];

for (const line of text.split(/\r?\n/)) {
  const match = line.match(/^(\d+)\s+(系所|學院)\s+(.+?)\s+(https:\/\/[^\s]+)/);
  if (!match) continue;

  const [, number, unitType, label, rawUrl] = match;
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    continue;
  }

  if (url.hostname !== 'nycu.edu.tw' && !url.hostname.endsWith('.nycu.edu.tw')) continue;
  url.hash = '';
  entries.push({
    number: Number(number),
    unitType,
    label: label.replace(/\s+/g, ' ').trim(),
    normalizedLabel: normalize(label),
    websiteUrl: url.href,
  });
}

const deduped = [...new Map(entries.map((entry) => [`${entry.number}:${entry.websiteUrl}`, entry])).values()]
  .sort((left, right) => left.number - right.number);

writeFileSync(outputPath, `${JSON.stringify(deduped, null, 2)}\n`);
console.log(`Wrote ${deduped.length} official NYCU college/department rows.`);
