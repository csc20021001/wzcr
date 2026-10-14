import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const sourcePath = resolve('db/faculty-pages.generated.json');
const outputPath = resolve('db/professor-candidates.generated.json');
const facultyPages = JSON.parse(readFileSync(sourcePath, 'utf8'));
const officialDomains = new Map([
  ['ntu', 'ntu.edu.tw'], ['nthu', 'nthu.edu.tw'], ['nycu', 'nycu.edu.tw'],
  ['ncu', 'ncu.edu.tw'], ['nchu', 'nchu.edu.tw'],
  ['ccu', 'ccu.edu.tw'], ['nsysu', 'nsysu.edu.tw'], ['ntust', 'ntust.edu.tw'],
  ['ntut', 'ntut.edu.tw'], ['niu', 'niu.edu.tw'],
]);

const rankPattern = /(終身特聘教授|特聘教授|講座教授|名譽教授|榮譽教授|教授|副教授|助理教授|專案教師|教學研究教師|講師)/;
const rejectedNamePattern = /(大學|學院|學系|系所|研究所|學程|專班|中心|辦公室|實驗室|研究室|專任|兼任|合聘|名譽|榮譽|榮退|退休|教師|師資|教授|講師|主任|院長|所長|系主任|職稱|姓名|成員|行政|秘書|助教|博士|碩士|學士|學歷|經歷|專長|領域|課程|招生|公告|更多|資料|介紹|簡介|信箱|電話|分機|著作|研究|國立|國家|國際|國外|臺灣|台灣|科技|工程|科學|管理|法律|醫學|教育|社會|人文|藝術|設計|生物|化學|物理|數學|資訊|電機|機械|土木|外文|中文|文學|文化|歷史|校友|系友|學生|最新消息|常見問題|網站導覽|回首頁|回頂端|聯絡我們|特聘|講座|助理|客座|職位|名單|須附|首頁|學者|人員|單位|學科|級專|兼系|專業技術|徵聘啟事|本所|指導|財管系|常用|相關|關於|表單|連結|資源|地址|消息|平面圖|技術|目標|實習|畢業|出路|農場|分子|簡史)/;
const commonSurnameChars = new Set('趙錢孫李周吳鄭王馮陳褚衛蔣沈韓楊朱秦尤許何呂施張孔曹嚴華金魏陶姜戚謝鄒喻柏水竇章雲蘇潘葛奚范彭郎魯韋昌馬苗鳳花方俞任袁柳鮑史唐費廉岑薛雷賀倪湯滕殷羅畢郝鄔安常樂于時傅皮卞齊康伍余元卜顧孟平黃和穆蕭尹姚邵汪祁毛禹狄米貝明臧計伏成戴談宋茅龐熊紀舒屈項祝董梁杜阮藍閔席季麻強賈路婁危江童顏郭梅盛林刁鍾徐丘駱高夏蔡田樊胡凌霍虞萬支柯管盧莫房裘繆解應宗丁宣鄧郁單杭洪包諸左石崔吉鈕龔程嵇邢滑裴陸榮翁荀羊甄曲家封芮儲靳汲段富巫焦巴弓牧山谷車侯全班仰秋仲伊宮寧仇欒甘祖武符劉景詹束龍葉幸司韶黎喬蒼聞莘黨翟譚貢勞姬申扶冉酈雍桑桂牛壽通邊扈燕浦尚農溫別莊晏柴瞿閻艾魚容向古易慎戈廖庾居衡步都耿滿弘匡國文寇廣祿闕東歐沃利蔚越隆師鞏聶晁勾敖融冷辛闞那簡饒曾沙養鞠豐巢關相查後荊紅游竺權益桓公'.split(''));
const compositeSurnames = ['歐陽', '司馬', '上官', '夏侯', '諸葛', '東方', '皇甫', '公孫', '慕容', '司徒', '司空', '端木', '百里', '宇文', '長孫', '令狐', '鍾離'];
const japaneseSurnames = ['佐藤', '大井', '服部', '山內', '藤井', '高橋', '鈴木', '田中', '山田', '渡邊', '伊藤', '小林', '加藤', '吉田', '山本', '松本', '井上', '木村', '清水', '山口', '中村', '石井', '齋藤'];

function plausiblePersonalName(name, sameLineEvidence) {
  if (commonSurnameChars.has(name[0]) || compositeSurnames.some((surname) => name.startsWith(surname))) return true;
  return sameLineEvidence && japaneseSurnames.some((surname) => name.startsWith(surname));
}

function decodeHtml(value) {
  return value
    .replace(/&#(\d+);/g, (_, number) => String.fromCodePoint(Number(number)))
    .replace(/&#x([0-9a-f]+);/gi, (_, number) => String.fromCodePoint(Number.parseInt(number, 16)))
    .replaceAll('&nbsp;', ' ').replaceAll('&amp;', '&').replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>');
}

function htmlLines(html) {
  return decodeHtml(html
    .replace(/<script\b[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style\b[\s\S]*?<\/style>/gi, ' ')
    .replace(/<svg\b[\s\S]*?<\/svg>/gi, ' ')
    .replace(/<\/(?:address|article|aside|blockquote|div|dl|dt|dd|fieldset|figcaption|figure|footer|form|h[1-6]|header|li|main|nav|ol|p|section|table|tbody|td|tfoot|th|thead|tr|ul)>/gi, '\n')
    .replace(/<(?:br|hr)\s*\/?\s*>/gi, '\n')
    .replace(/<[^>]*>/g, ' '))
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}

function allowedSource(url, universityId) {
  const domain = officialDomains.get(universityId);
  const parsed = new URL(url);
  return Boolean(domain && parsed.protocol === 'https:' &&
    (parsed.hostname === domain || parsed.hostname.endsWith(`.${domain}`)));
}

function linkedFacultyNames(html) {
  const names = new Set();
  for (const match of html.matchAll(/<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    if (!/(faculty|teacher|professor|people|person|member|team|staff|師資|教師|成員)/i.test(match[1])) continue;
    const text = decodeHtml(match[2].replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ').trim();
    const name = text.match(/^([\u3400-\u9fff]{2,5})(?:\s*[（(][^）)]*[）)])?$/)?.[1];
    if (name) names.add(name);
  }
  return names;
}

function namesFromLines(lines, html) {
  const found = new Map();
  const linkedNames = linkedFacultyNames(html);
  const addCandidate = (rawName, rank, evidence, sameLineEvidence) => {
    const normalizedName = rawName.replace(/\s+/g, '').replace(/(約聘|專案|老師|醫師|院士|副)$/g, '');
    if (normalizedName.length < 2 || normalizedName.length > 5 || rejectedNamePattern.test(normalizedName)) return;
    if (/名譽|榮譽/.test(rank) || !plausiblePersonalName(normalizedName, sameLineEvidence)) return;
    if (/(演講|公告|恭喜|恭賀|榮獲|獲獎|得獎|徵聘|誠徵|應徵|徵才|研討會|工作坊|講題|學年度.*獎|新進教師介紹)/.test(evidence)) return;
    if (!found.has(normalizedName) || sameLineEvidence) {
      found.set(normalizedName, {
        name: normalizedName,
        rank,
        evidence: evidence.slice(0, 220),
        sameLineEvidence,
      });
    }
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const lineCandidates = [];
    const title = '(?:終身特聘教授|特聘教授|講座教授|名譽教授|榮譽教授|教授|副教授|助理教授|專案教師|教學研究教師|講師)';
    const name = '([\\u3400-\\u9fff](?:\\s*[\\u3400-\\u9fff]){1,4}?)';
    const afterName = new RegExp(`${name}\\s*(?:老師\\s*)?(?:職稱\\s*[:：]?\\s*)?(${title})`);
    const beforeName = new RegExp(`^\\s*(${title})\\s*[:：|｜-]?\\s+${name}(?:\\s|$)`);
    const afterMatch = line.match(afterName);
    if (afterMatch) lineCandidates.push({ name: afterMatch[1], rank: afterMatch[2], sameLineEvidence: true });
    const beforeMatch = line.match(beforeName);
    if (beforeMatch) lineCandidates.push({ name: beforeMatch[2], rank: beforeMatch[1], sameLineEvidence: true });

    const exactName = line.match(/^([\u3400-\u9fff](?:\s*[\u3400-\u9fff]){1,4})$/)?.[1];
    if (exactName) {
      const nextLine = lines[index + 1] ?? '';
      const lineAfterRomanization = /^[A-Za-z .,'-]{2,80}$/.test(nextLine) ? (lines[index + 2] ?? '') : '';
      const followingRank = (nextLine.match(rankPattern) ?? lineAfterRomanization.match(rankPattern))?.[1];
      if (followingRank) lineCandidates.push({ name: exactName, rank: followingRank, sameLineEvidence: false });
    }

    const inlineLabeledName = line.match(/^姓名\s*[:：]\s*([\u3400-\u9fff]{2,5})/)?.[1];
    const labeledName = inlineLabeledName ?? (/^姓名\s*[:：]?\s*$/.test(line)
      ? (lines[index + 1] ?? '').match(/^([\u3400-\u9fff]{2,5})(?:\s*[（(][^）)]*[）)])?$/)?.[1]
      : null);
    if (labeledName) {
      const nearby = lines.slice(index + 2, index + 14);
      const titleIndex = nearby.findIndex((value) => /^職稱\s*[:：]?\s*$/.test(value));
      const nearbyRank = titleIndex >= 0
        ? nearby.slice(titleIndex + 1, titleIndex + 4).map((value) => value.match(rankPattern)?.[1]).find(Boolean)
        : nearby.map((value) => value.match(rankPattern)?.[1]).find(Boolean);
      if (nearbyRank) lineCandidates.push({ name: labeledName, rank: nearbyRank, sameLineEvidence: false });
    }

    const cardName = line.match(/^([\u3400-\u9fff]{2,5})\s*(?:>|›|»|→)$/)?.[1];
    if (cardName) {
      const nearby = lines.slice(index + 1, index + 6);
      const nearbyRank = nearby.map((value) => value.match(rankPattern)?.[1]).find(Boolean);
      if (nearbyRank) lineCandidates.push({ name: cardName, rank: nearbyRank, sameLineEvidence: false });
    }

    for (const candidate of lineCandidates) {
      addCandidate(candidate.name, candidate.rank, line, candidate.sameLineEvidence);
    }
  }

  let inFullTimeSection = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (/^(專任師資|專任教師|專任教員|full-?timefaculty)$/i.test(line.replace(/\s+/g, ''))) {
      inFullTimeSection = true;
      continue;
    }
    if (inFullTimeSection && /^(合聘|兼任|名譽|榮譽|退休|行政|系辦|助教|職員|staff)/i.test(line.replace(/\s+/g, ''))) {
      inFullTimeSection = false;
      continue;
    }
    if (!inFullTimeSection) continue;
    const sectionName = line.match(/^([\u3400-\u9fff]{2,5})(?:\s*[（(][^）)]*[）)])?$/)?.[1];
    if (sectionName && linkedNames.has(sectionName)) addCandidate(sectionName, '專任教師', line, false);
  }

  for (let start = 0; start < lines.length; start += 1) {
    if (!/^(專任師資|專任教師|專任教員|full-?timefaculty)$/i.test(lines[start].replace(/\s+/g, ''))) continue;
    const relativeStop = lines.slice(start + 1, start + 121)
      .findIndex((line) => /^(合聘|兼任|名譽|榮譽|退休|行政|系辦|助教|職員|staff)/i.test(line.replace(/\s+/g, '')));
    if (relativeStop < 0) continue;
    const stop = start + 1 + relativeStop;
    for (const line of lines.slice(start + 1, stop)) {
      const sectionName = line.match(/^([\u3400-\u9fff]{2,5})(?:\s*[（(][^）)]*[）)])?$/)?.[1];
      if (sectionName) addCandidate(sectionName, '專任教師', line, false);
    }
  }
  return [...found.values()];
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: { 'User-Agent': 'WZUNAA official faculty directory builder/1.0 (+https://map.scmwcscr.com)' },
    signal: AbortSignal.timeout(20_000),
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

function eligibleFacultyPage(row) {
  if (!row.facultyPageUrl) return false;
  if (row.facultyMatchScore >= 820) return true;
  const text = String(row.facultyLinkText ?? '').normalize('NFKC').replace(/\s+/g, '').toLowerCase();
  const safeText = /^(教師專區|現任教師|本院師資|學程教師faculty|學程師資|教師團隊|師資簡介|師資|faculty|faculty&staffs?|系所成員faculty|本系成員people|系所成員|本系成員|師資人員|本所成員|師資研究|化工師資|師資總覽|教師總表|師資現況|系所教師|授課師資|教師成員|本系教師|本班教師|教師)$/i.test(text);
  const safePath = /(faculty|teacher|professor|members?|people|staff|team)/i.test(row.facultyPageUrl);
  return safeText && (row.facultyMatchScore >= 700 || safePath);
}

const eligibleRows = facultyPages.filter(eligibleFacultyPage);
const uniquePages = [...new Map(eligibleRows.map((row) => [`${row.universityId}\u0000${row.facultyPageUrl}`, row])).values()];
console.log(`Opening ${uniquePages.length} high-confidence official faculty page(s).`);

const pageResults = await mapConcurrent(uniquePages, 8, async (row, index) => {
  try {
    const { html, finalUrl } = await fetchText(row.facultyPageUrl);
    if (!allowedSource(finalUrl, row.universityId)) throw new Error('redirected outside the official university domain');
    const names = namesFromLines(htmlLines(html), html);
    if ((index + 1) % 25 === 0) console.log(`Parsed ${index + 1}/${uniquePages.length}`);
    return { key: `${row.universityId}\u0000${row.facultyPageUrl}`, finalUrl, names, fetchError: null };
  } catch (error) {
    return {
      key: `${row.universityId}\u0000${row.facultyPageUrl}`,
      finalUrl: row.facultyPageUrl,
      names: [],
      fetchError: error instanceof Error ? error.message : String(error),
    };
  }
});

const byPage = new Map(pageResults.map((row) => [row.key, row]));
const candidates = [];
const seen = new Set();
for (const unit of eligibleRows) {
  const page = byPage.get(`${unit.universityId}\u0000${unit.facultyPageUrl}`);
  if (!page || page.fetchError) continue;
  for (const person of page.names) {
    const identity = `${unit.universityId}\u0000${unit.name}\u0000${person.name}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    candidates.push({
      universityId: unit.universityId,
      department: unit.name,
      name: person.name,
      rank: person.rank,
      sourceUrl: page.finalUrl,
      evidence: person.evidence,
      sameLineEvidence: person.sameLineEvidence,
    });
  }
}

writeFileSync(outputPath, `${JSON.stringify(candidates, null, 2)}\n`);
const schools = new Set(candidates.map((row) => row.universityId));
const departments = new Set(candidates.map((row) => `${row.universityId}\u0000${row.department}`));
console.log(`Wrote ${candidates.length} candidate(s) from ${departments.size} department(s) across ${schools.size} school(s).`);
