import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const sourcePath = resolve('db/department-sites.generated.json');
const outputPath = resolve('db/faculty-pages.generated.json');
const departmentSites = JSON.parse(readFileSync(sourcePath, 'utf8'));
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
    .replaceAll('&nbsp;', ' ').replaceAll('&amp;', '&').replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>');
}

function stripTags(value) {
  return decodeHtml(value.replace(/<script\b[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style\b[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]*>/g, ' '))
    .replace(/\s+/g, ' ').trim();
}

function allowedUrl(value, universityId) {
  const domain = officialDomains.get(universityId);
  return Boolean(domain && value.protocol === 'https:' &&
    (value.hostname === domain || value.hostname.endsWith(`.${domain}`)));
}

function facultyScore(text, href) {
  const normalized = text.normalize('NFKC').replace(/\s+/g, '').toLowerCase();
  const normalizedHref = href.toLowerCase();
  if (/(兼任|名譽|榮譽|退休|行政|學生|系友|校友|徵才|徵聘|誠徵|誠聘|應徵|徵求|招聘|榮獲|恭賀|得獎|獲獎|教學優良獎|公告|發布日期|新進教師|facultyposition|facultyopening)/.test(normalized)) return 0;
  if (/(honou?r|award|recruit|faculty-position|faculty_position|faculty-opening)/.test(normalizedHref)) return 0;
  let score = 0;
  if (/^(專任師資|專任教師|專任教員|full-?timefaculty)$/.test(normalized)) score += 1000;
  else if (/專任.*(師資|教師|教員)|(師資|教師|教員).*專任/.test(normalized)) score += 900;
  else if (/(師資一覽表|師資名錄|教師名錄)/.test(normalized)) score += 900;
  else if (/(師資陣容|師資介紹|教師陣容|教師介紹|師資成員|教師成員|師資總表|現任師資|系所師資)/.test(normalized)) score += 820;
  else if (/(師資|教師|教員|faculty|professor)/.test(normalized)) score += 700;
  else if (/(系所成員|系所成員|成員介紹|team|people)/.test(normalized)) score += 480;
  if (/(faculty|teacher|professor|people|member|staff|師資|教師)/.test(normalizedHref)) score += 240;
  if (/(full|專任)/.test(normalizedHref)) score += 120;
  return score;
}

function facultyLinks(html, baseUrl, universityId) {
  const links = [];
  for (const match of html.matchAll(/<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const text = stripTags(match[2]);
    let url;
    try { url = new URL(decodeHtml(match[1]).trim(), baseUrl); } catch { continue; }
    if (!allowedUrl(url, universityId) || /\.(pdf|docx?|xlsx?|zip|jpe?g|png)(?:$|\?)/i.test(url.pathname)) continue;
    url.hash = '';
    const score = facultyScore(text, url.href);
    if (score > 0) links.push({ text, url: url.href, score });
  }
  return links.sort((left, right) => right.score - left.score || left.url.length - right.url.length);
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: { 'User-Agent': 'WZUNAA official faculty directory builder/1.0 (+https://map.scmwcscr.com)' },
    signal: AbortSignal.timeout(18_000),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return { html: await response.text(), finalUrl: response.url };
}

async function mapConcurrent(items, concurrency, worker) {
  const results = new Array(items.length);
  let next = 0;
  async function run() {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, run));
  return results;
}

const eligible = departmentSites.filter((row) => row.websiteUrl && row.matchScore >= 700);
const uniqueSites = [...new Map(eligible.map((row) => [`${row.universityId}\u0000${row.websiteUrl}`, row])).values()];
console.log(`Opening ${uniqueSites.length} unique official department site(s).`);

const discoveries = await mapConcurrent(uniqueSites, 8, async (row, index) => {
  try {
    const { html, finalUrl } = await fetchText(row.websiteUrl);
    const links = facultyLinks(html, finalUrl, row.universityId);
    const best = links[0] ?? null;
    if ((index + 1) % 25 === 0) console.log(`Opened ${index + 1}/${uniqueSites.length}`);
    return {
      key: `${row.universityId}\u0000${row.websiteUrl}`,
      facultyPageUrl: best?.url ?? null,
      matchedOfficialText: best?.text ?? null,
      matchScore: best?.score ?? 0,
      finalDepartmentUrl: finalUrl,
      fetchError: null,
    };
  } catch (error) {
    return {
      key: `${row.universityId}\u0000${row.websiteUrl}`,
      facultyPageUrl: null,
      matchedOfficialText: null,
      matchScore: 0,
      finalDepartmentUrl: row.websiteUrl,
      fetchError: error instanceof Error ? error.message : String(error),
    };
  }
});

const byKey = new Map(discoveries.map((row) => [row.key, row]));
const rows = departmentSites.map((row) => {
  const discovery = row.websiteUrl ? byKey.get(`${row.universityId}\u0000${row.websiteUrl}`) : null;
  return {
    ...row,
    finalDepartmentUrl: discovery?.finalDepartmentUrl ?? row.websiteUrl,
    facultyPageUrl: discovery?.facultyPageUrl ?? null,
    facultyLinkText: discovery?.matchedOfficialText ?? null,
    facultyMatchScore: discovery?.matchScore ?? 0,
    fetchError: discovery?.fetchError ?? null,
  };
});

writeFileSync(outputPath, `${JSON.stringify(rows, null, 2)}\n`);
const resolved = rows.filter((row) => row.facultyPageUrl).length;
const failed = rows.filter((row) => row.fetchError).length;
console.log(`Wrote ${rows.length} unit rows: ${resolved} faculty page(s), ${failed} failed fetch(es).`);
