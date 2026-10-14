import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { departmentSeeds } from '../db/department-seeds.ts';

const outputPath = resolve('db/department-sites.generated.json');
const nycuDirectoryPath = resolve('db/nycu-official-units.generated.json');
const officialDomains = new Map([
  ['ntu', 'ntu.edu.tw'], ['nthu', 'nthu.edu.tw'], ['nycu', 'nycu.edu.tw'],
  ['ncu', 'ncu.edu.tw'], ['nchu', 'nchu.edu.tw'],
  ['ccu', 'ccu.edu.tw'], ['nsysu', 'nsysu.edu.tw'], ['ntust', 'ntust.edu.tw'],
  ['ntut', 'ntut.edu.tw'], ['niu', 'niu.edu.tw'],
]);

function decodeHtml(value) {
  return value
    .replace(/&#(\d+);/g, (_, number) => String.fromCodePoint(Number(number)))
    .replace(/&#x([0-9a-f]+);/gi, (_, number) => String.fromCodePoint(Number.parseInt(number, 16)))
    .replaceAll('&nbsp;', ' ')
    .replaceAll('&amp;', '&')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>');
}

function stripTags(value) {
  return decodeHtml(value.replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ').trim();
}

function normalize(value) {
  return stripTags(value)
    .normalize('NFKC')
    .replaceAll('台', '臺')
    .replace(/[（(].*?[）)]/g, '')
    .replace(/[\s\-—–_、，,。．・·/]/g, '')
    .toLowerCase();
}

function baseName(value) {
  return normalize(value)
    .replace(/(碩士|博士|學士)?(在職)?(學位)?學程$/g, '')
    .replace(/(碩士|博士|學士)?(在職)?專班$/g, '')
    .replace(/暨.*研究所$/g, '')
    .replace(/(學系|研究所|系|所|學院)$/g, '');
}

function allowedUrl(value, universityId) {
  const domain = officialDomains.get(universityId);
  if (!domain || value.protocol !== 'https:') return false;
  return value.hostname === domain || value.hostname.endsWith(`.${domain}`);
}

function anchorsFromHtml(html, baseUrl, universityId) {
  const anchors = [];
  for (const match of html.matchAll(/<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const text = stripTags(match[2]);
    if (!text || /^(更多|more|top|回首頁|首頁|網站導覽)$/i.test(text)) continue;
    let url;
    try { url = new URL(decodeHtml(match[1]).trim(), baseUrl); } catch { continue; }
    if (!allowedUrl(url, universityId) || /\.(pdf|docx?|xlsx?|zip)(?:$|\?)/i.test(url.pathname)) continue;
    url.hash = '';
    anchors.push({ text, url: url.href, normalized: normalize(text), base: baseName(text) });
  }
  return anchors;
}

function matchScore(unit, anchor) {
  const normalizedUnit = normalize(unit.name);
  const unitBase = baseName(unit.name);
  if (!normalizedUnit || !anchor.normalized) return 0;
  if (anchor.normalized === normalizedUnit) return 1000;
  if (anchor.normalized.includes(normalizedUnit)) return 800 + normalizedUnit.length;
  if (normalizedUnit.includes(anchor.normalized) && anchor.normalized.length >= 4) return 700 + anchor.normalized.length;
  if (unitBase.length >= 3 && anchor.base === unitBase) return 650 + unitBase.length;
  if (unitBase.length >= 4 && anchor.base.includes(unitBase)) return 500 + unitBase.length;
  if (anchor.base.length >= 4 && unitBase.includes(anchor.base)) return 450 + anchor.base.length;
  return 0;
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: { 'User-Agent': 'WZUNAA official academic directory builder/1.0 (+https://map.scmwcscr.com)' },
    signal: AbortSignal.timeout(25_000),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return { html: await response.text(), finalUrl: response.url };
}

const sourceUrls = [...new Set(departmentSeeds.map((seed) => seed.sourceUrl))];
const sourceAnchors = new Map();
for (const sourceUrl of sourceUrls) {
  const universityId = departmentSeeds.find((seed) => seed.sourceUrl === sourceUrl)?.universityId;
  if (!universityId) continue;
  try {
    const { html, finalUrl } = await fetchText(sourceUrl);
    sourceAnchors.set(sourceUrl, anchorsFromHtml(html, finalUrl, universityId));
    console.log(`${universityId}: ${sourceAnchors.get(sourceUrl).length} official link(s)`);
  } catch (error) {
    console.warn(`${universityId}: failed to open ${sourceUrl}: ${error instanceof Error ? error.message : error}`);
    sourceAnchors.set(sourceUrl, []);
  }
}

if (existsSync(nycuDirectoryPath)) {
  const nycuEntries = JSON.parse(readFileSync(nycuDirectoryPath, 'utf8'));
  const sourceUrl = departmentSeeds.find((seed) => seed.universityId === 'nycu')?.sourceUrl;
  if (sourceUrl) {
    const supplemental = nycuEntries.map((entry) => ({
      text: entry.label,
      url: entry.websiteUrl,
      normalized: normalize(entry.label),
      base: baseName(entry.label),
    }));
    sourceAnchors.set(sourceUrl, [...(sourceAnchors.get(sourceUrl) ?? []), ...supplemental]);
    console.log(`nycu: added ${supplemental.length} official PDF directory link(s)`);
  }
}

const rows = departmentSeeds.map((unit) => {
  const matches = (sourceAnchors.get(unit.sourceUrl) ?? [])
    .map((anchor) => ({ ...anchor, score: matchScore(unit, anchor) }))
    .filter((anchor) => anchor.score > 0)
    .sort((left, right) => right.score - left.score || left.url.length - right.url.length);
  const match = matches[0] ?? null;
  return {
    departmentId: unit.id,
    universityId: unit.universityId,
    college: unit.college,
    name: unit.name,
    officialDirectoryUrl: unit.sourceUrl,
    websiteUrl: match?.url ?? null,
    matchedOfficialText: match?.text ?? null,
    matchScore: match?.score ?? 0,
  };
});

writeFileSync(outputPath, `${JSON.stringify(rows, null, 2)}\n`);
const resolved = rows.filter((row) => row.websiteUrl).length;
console.log(`Wrote ${rows.length} unit rows: ${resolved} resolved, ${rows.length - resolved} unresolved.`);
