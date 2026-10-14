import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cache = path.join(root, '.place-course-cache');
const [school, term] = process.argv.slice(2);

if (!/^(?:nknu|nptu|tnnua)$/.test(school || '') || !/^\d{3}[12]$/.test(term || '')) {
  throw new Error('Usage: node scripts/fetch-official-webforms.mjs <nknu|nptu|tnnua> <YYY1|YYY2>');
}

await mkdir(cache, { recursive: true });

const headers = {
  'user-agent': 'WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)',
  'accept-language': 'zh-TW,zh;q=0.9,en;q=0.5',
};

function decodeAttribute(value = '') {
  return value
    .replaceAll('&amp;', '&')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>');
}

function attribute(tag, name) {
  const match = tag.match(new RegExp(`\\b${name}\\s*=\\s*(["'])(.*?)\\1`, 'i'));
  return match ? decodeAttribute(match[2]) : '';
}

function hiddenFields(html) {
  const result = {};
  for (const tag of html.match(/<input\b[^>]*>/gi) || []) {
    if (attribute(tag, 'type').toLowerCase() !== 'hidden') continue;
    const name = attribute(tag, 'name');
    if (name) result[name] = attribute(tag, 'value');
  }
  return result;
}

function formAction(html, base) {
  const tag = (html.match(/<form\b[^>]*>/i) || [])[0];
  if (!tag) throw new Error(`${school} response has no form`);
  return new URL(attribute(tag, 'action') || base, base).href;
}

function decodeBuffer(body) {
  const prefix = body.subarray(0, 4096).toString('latin1');
  const match = prefix.match(/charset\s*=\s*["']?([a-z0-9_-]+)/i);
  const charset = /big5|950/i.test(match?.[1] || '') ? 'big5' : 'utf-8';
  return new TextDecoder(charset).decode(body);
}

function responseCookies(response) {
  const values = typeof response.headers.getSetCookie === 'function'
    ? response.headers.getSetCookie()
    : [response.headers.get('set-cookie')].filter(Boolean);
  return values.map((value) => value.split(';', 1)[0]).join('; ');
}

async function getSession(url) {
  const response = await fetch(url, { headers, redirect: 'error' });
  if (!response.ok) throw new Error(`${school} initial GET failed: ${response.status}`);
  const body = Buffer.from(await response.arrayBuffer());
  return { body, html: body.toString('utf8'), cookie: responseCookies(response) };
}

async function postForm(url, cookie, fields) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      ...headers,
      'content-type': 'application/x-www-form-urlencoded',
      cookie,
      origin: new URL(url).origin,
      referer: url,
    },
    body: new URLSearchParams(fields),
    redirect: 'error',
  });
  if (!response.ok) throw new Error(`${school} POST failed: ${response.status}`);
  const body = Buffer.from(await response.arrayBuffer());
  return { body, html: body.toString('utf8') };
}

async function fetchNknu() {
  const url = 'https://sso.nknu.edu.tw/Stu/scheduleSubject.aspx';
  const initial = await getSession(url);
  const year = term.slice(0, 3);
  const semester = term.slice(3);
  let count = 0;
  for (const division of ['D', 'N']) {
    const fields = {
      ...hiddenFields(initial.html),
      'ctl00$phMain$uDN': division,
      'ctl00$phMain$uYearSemester$uYear': year,
      'ctl00$phMain$uYearSemester$uSemester': semester,
      'ctl00$phMain$uCourseName': '%',
      'ctl00$phMain$uSearch': '查詢',
    };
    const result = await postForm(url, initial.cookie, fields);
    if (!result.html.includes('ctl00_phMain_uScheduleList_uList') || !/syllabusForEnro\.aspx/i.test(result.html)) {
      throw new Error(`NKNU returned no course rows for ${term}/${division}`);
    }
    await writeFile(path.join(cache, `nknu-${term}-${division}.html`), result.body);
    count += 1;
  }
  await writeFile(
    path.join(cache, `nknu-${term}-manifest.json`),
    JSON.stringify({ school: 'nknu', term, files: count }) + '\n',
  );
}

async function fetchTnnua() {
  const url = 'https://ap.tnnua.edu.tw/CourseInfo/CourseList.aspx';
  const initial = await getSession(url);
  const year = term.slice(0, 3);
  const semester = term.slice(3);
  const baseFields = {
    'ctl00$MainContent$ddlYear': year,
    'ctl00$MainContent$ddlSems': semester,
    'ctl00$MainContent$ddlCollege': '0',
    'ctl00$MainContent$ddlWeek': '0',
    'ctl00$MainContent$ddlSection': '0',
    'ctl00$MainContent$ddlCourseCategory': '0',
    'ctl00$MainContent$txtCourseName': '',
    'ctl00$MainContent$txtCourseCode': '',
    'ctl00$MainContent$txtTeacherName': '',
  };
  let result = await postForm(url, initial.cookie, {
    ...hiddenFields(initial.html),
    ...baseFields,
    'ctl00$MainContent$btnQuery': '查詢',
  });
  if (!result.html.includes('MainContent_gv') || !/Print_Course_Syllabus\.aspx/i.test(result.html)) {
    throw new Error(`TNNUA returned no course rows for ${term}`);
  }
  let page = 1;
  await writeFile(path.join(cache, `tnnua-${term}-${String(page).padStart(3, '0')}.html`), result.body);
  for (;;) {
    const pageNumbers = [...result.html.matchAll(/Page\$(\d+)/gi)]
      .map((match) => Number.parseInt(match[1], 10))
      .filter(Number.isInteger);
    if (!pageNumbers.some((value) => value > page)) break;
    if (++page > 500) throw new Error(`TNNUA pagination exceeded safety limit for ${term}`);
    result = await postForm(url, initial.cookie, {
      ...hiddenFields(result.html),
      ...baseFields,
      __EVENTTARGET: 'ctl00$MainContent$gv',
      __EVENTARGUMENT: `Page$${page}`,
    });
    if (!result.html.includes('MainContent_gv')) {
      throw new Error(`TNNUA pager lost its result table for ${term}/${page}`);
    }
    await writeFile(path.join(cache, `tnnua-${term}-${String(page).padStart(3, '0')}.html`), result.body);
  }
  await writeFile(
    path.join(cache, `tnnua-${term}-manifest.json`),
    JSON.stringify({ school: 'tnnua', term, files: page }) + '\n',
  );
}

async function fetchNptu() {
  const cookies = new Map();

  function cookieHeader() {
    return [...cookies.entries()].map(([name, value]) => `${name}=${value}`).join('; ');
  }

  function acceptCookies(response) {
    const values = typeof response.headers.getSetCookie === 'function'
      ? response.headers.getSetCookie()
      : [response.headers.get('set-cookie')].filter(Boolean);
    for (const value of values) {
      const pair = value.split(';', 1)[0];
      const separator = pair.indexOf('=');
      if (separator > 0) cookies.set(pair.slice(0, separator), pair.slice(separator + 1));
    }
  }

  async function request(url, { method = 'GET', fields, referer } = {}) {
    let target = new URL(url).href;
    let requestMethod = method;
    let requestBody = fields ? new URLSearchParams(fields) : undefined;
    for (let redirect = 0; redirect < 8; redirect += 1) {
      const parsed = new URL(target);
      if (parsed.protocol !== 'https:' || !(parsed.hostname === 'nptu.edu.tw' || parsed.hostname.endsWith('.nptu.edu.tw'))) {
        throw new Error(`NPTU rejected non-official redirect: ${target}`);
      }
      const response = await fetch(target, {
        method: requestMethod,
        headers: {
          ...headers,
          ...(requestBody ? { 'content-type': 'application/x-www-form-urlencoded' } : {}),
          ...(cookieHeader() ? { cookie: cookieHeader() } : {}),
          ...(referer ? { referer } : {}),
        },
        body: requestBody,
        redirect: 'manual',
      });
      acceptCookies(response);
      if (response.status >= 300 && response.status < 400 && response.headers.get('location')) {
        target = new URL(response.headers.get('location'), target).href;
        if (response.status === 301 || response.status === 302 || response.status === 303) {
          requestMethod = 'GET';
          requestBody = undefined;
        }
        continue;
      }
      if (!response.ok) throw new Error(`NPTU request failed: ${response.status} ${target}`);
      const body = Buffer.from(await response.arrayBuffer());
      return { url: target, body, html: decodeBuffer(body) };
    }
    throw new Error(`NPTU redirect limit exceeded: ${url}`);
  }

  const landing = await request('https://webap.nptu.edu.tw/Web/Secure/default.aspx?SIndex=7');
  const guestInput = (landing.html.match(/<input\b[^>]*>/gi) || [])
    .find((tag) => /LoginGuest\.gif/i.test(attribute(tag, 'src')));
  const guestName = guestInput ? attribute(guestInput, 'name') : '';
  if (!guestName) throw new Error('NPTU guest button is unavailable');
  const login = await request(formAction(landing.html, landing.url), {
    method: 'POST',
    referer: landing.url,
    fields: {
      ...hiddenFields(landing.html),
      [`${guestName}.x`]: '1',
      [`${guestName}.y`]: '1',
      'LoginDefault:txtScreenWidth': '1920',
      'LoginDefault:txtScreenHeight': '1080',
    },
  });
  const message = await request(new URL('../Message/default.aspx', login.url).href, { referer: login.url });
  const mainFrame = (message.html.match(/<frame\b[^>]*>/gi) || [])
    .find((tag) => attribute(tag, 'name').toLowerCase() === 'main');
  if (!mainFrame) throw new Error('NPTU main frame is unavailable');
  const main = await request(new URL(attribute(mainFrame, 'src'), message.url).href, { referer: message.url });
  const gstInput = (main.html.match(/<input\b[^>]*>/gi) || [])
    .find((tag) => /GST_M\.gif/i.test(attribute(tag, 'src')));
  const gstName = gstInput ? attribute(gstInput, 'name') : '';
  if (!gstName) throw new Error('NPTU guest course menu is unavailable');
  const submenu = await request(formAction(main.html, main.url), {
    method: 'POST',
    referer: main.url,
    fields: {
      ...hiddenFields(main.html),
      [`${gstName}.x`]: '1',
      [`${gstName}.y`]: '1',
    },
  });
  const courseAnchor = (submenu.html.match(/<a\b[^>]*>.*?<\/a>/gis) || [])
    .find((tag) => /\[A0428S\]/i.test(tag.replace(/<[^>]+>/g, '')));
  const postback = decodeAttribute(courseAnchor ? attribute(courseAnchor, 'href') : '')
    .match(/__doPostBack\('([^']+)','([^']*)'\)/);
  if (!postback) throw new Error('NPTU course-query postback is unavailable');
  const queryForm = await request(formAction(submenu.html, submenu.url), {
    method: 'POST',
    referer: submenu.url,
    fields: {
      ...hiddenFields(submenu.html),
      __EVENTTARGET: postback[1],
      __EVENTARGUMENT: postback[2],
    },
  });
  const result = await request(formAction(queryForm.html, queryForm.url), {
    method: 'POST',
    referer: queryForm.url,
    fields: {
      ...hiddenFields(queryForm.html),
      'A0425Q3:ddlSYSE': term,
      'A0425Q3:ddlDEPT_ID': '',
      'A0425Q3:ddlENG_TAUGHT_YN': '',
      'A0425Q3:ddlCOMMON_ID': '',
      'A0425Q3:ddlSCH_SYS_M': '',
      'A0425Q3:ddlWEEK_ID': '',
      'A0425Q3:txtSUBJ_CNAME': '%',
      'A0425Q3:txtEMP_CNAME': '',
      'A0425Q3:ibtQuery.x': '1',
      'A0425Q3:ibtQuery.y': '1',
    },
  });
  if (!result.html.includes('A0425S3_dgData')) {
    throw new Error(`NPTU returned no official result table for ${term}`);
  }
  await writeFile(path.join(cache, `nptu-${term}.html`), result.body);
  await writeFile(
    path.join(cache, `nptu-${term}-manifest.json`),
    JSON.stringify({ school: 'nptu', term, files: 1 }) + '\n',
  );
}

if (school === 'nknu') await fetchNknu();
if (school === 'nptu') await fetchNptu();
if (school === 'tnnua') await fetchTnnua();
