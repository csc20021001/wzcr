"""Build a verified course snapshot from university-owned public data only.

The generator intentionally rejects an offering unless at least one instructor
is still present in the university's current official faculty-directory crawl.
Raw downloads are cached outside the application bundle in .course-cache.
"""

from __future__ import annotations

import base64
import hashlib
import html
import concurrent.futures
import http.cookiejar
import io
import json
import re
import ssl
import subprocess
import sys
import tarfile
import threading
import time
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".course-cache"
DB = ROOT / "db"
CURRENT_YEAR = 115
EARLIEST_YEAR = 106
TERM_PAIRS = tuple((year, semester) for year in range(EARLIEST_YEAR, CURRENT_YEAR) for semester in (1, 2)) + ((CURRENT_YEAR, 1),)
COMPLETION_MIGRATION_BATCH = 1
ALLOWED_HOST_SUFFIXES = {
    "ntu": ("ntu.edu.tw",),
    "nthu": ("nthu.edu.tw",),
    "ccu": ("ccu.edu.tw",),
    "ncu": ("ncu.edu.tw",),
    "nchu": ("nchu.edu.tw",),
    "nycu": ("nycu.edu.tw",),
    "nsysu": ("nsysu.edu.tw",),
    "ntust": ("ntust.edu.tw",),
    "ntut": ("ntut.edu.tw",),
    "niu": ("niu.edu.tw",),
}

NTHU_SOURCES = (
    ("nthu-108-110.xlsx", "https://curricul.site.nthu.edu.tw/var/file/208/1208/img/1657/108-110coursedata_n%283%29.xlsx"),
    ("nthu-1091-1111.json", "https://curricul.site.nthu.edu.tw/var/file/208/1208/img/474/unicode_1091_1111.json"),
    ("nthu-1112-1122.json", "https://curricul.site.nthu.edu.tw/var/file/208/1208/img/474/11120-11220JSON.json"),
    ("nthu-111-113.xlsx", "https://curricul.site.nthu.edu.tw/var/file/208/1208/img/1657/111all-113all_courses_redo.xlsx"),
    ("nthu-1141.xlsx", "https://curricul.site.nthu.edu.tw/var/file/208/1208/img/1350/11410_course_data_fin.xlsx"),
    ("nthu-1151.json", "https://www.ccxp.nthu.edu.tw/ccxp/INQUIRE/JH/OPENDATA/open_course_data.json"),
)

NYCU_OFFICIAL_SITE = "https://coz.aa.nycu.edu.tw"
NTUST_API = "https://querycourse.ntust.edu.tw/QueryCourse/api"

CCU_TERMS = tuple(f"{year}{semester}" for year in range(EARLIEST_YEAR, 115) for semester in (1, 2)) + ("1151",)

COURSE_SOURCE_STATUS = {
    "ntu": {"status": "imported", "officialIndex": "https://nol.ntu.edu.tw/nol/guest/main.php", "note": "校方課程網公開歷史查詢"},
    "nthu": {"status": "imported", "officialIndex": "https://curricul.site.nthu.edu.tw/p/404-1208-111356.php?Lang=zh-tw", "note": "官方下載檔目前涵蓋 108 至 115-1"},
    "nycu": {"status": "imported", "officialIndex": "https://coz.aa.nycu.edu.tw/", "note": "校方公開 sitemap 逐筆核對 106 至 115-1 課程頁"},
    "ncu": {"status": "imported", "officialIndex": "https://cis.ncu.edu.tw/Course/main/query/byYears", "note": "官方逐年逐系歷史課表"},
    "nchu": {"status": "imported", "officialIndex": "https://onepiece.nchu.edu.tw/cofsys/plsql/crseqry_home", "note": "校方目前公開 115-1 全學制課表；舊學期選項目前回傳空表"},
    "ccu": {"status": "imported", "officialIndex": "https://kiki.ccu.edu.tw/~ccmisp06/Course/zipfiles/", "note": "逐學期官方壓縮檔"},
    "nsysu": {"status": "restricted", "officialIndex": "https://selcrs.nsysu.edu.tw/menu1/CourseQuery.asp?HIS=1&eng=0", "note": "官方歷史查詢要求人工驗證碼，未繞過"},
    "ntust": {"status": "imported", "officialIndex": "https://querycourse.ntust.edu.tw/querycourse/", "note": "校方公開課程 API 涵蓋 106 至 115-1"},
    "ntut": {"status": "imported", "officialIndex": "https://aps.ntut.edu.tw/course/tw/QueryCurrPage.jsp", "note": "官方逐學期、逐開課單位歷史查詢"},
    "niu": {"status": "imported", "officialIndex": "https://academic.niu.edu.tw/p/403-1003-117-1.php", "note": "校級公開課表可逐學期匯出；目前匯入 106 至 115-1"},
}

LEGACY_COURSE_IDS = {
    ("ntu", "ChemE1001-01"): "course-ntu-cheme1001-01",
    ("ntu", "CHIN8012-01"): "course-ntu-chin8012-01",
    ("nthu", "AES 450100"): "course-nthu-aes450100",
    ("nthu", "AES 470200"): "course-nthu-aes470200",
    ("ncu", "MA1001-7"): "course-ncu-ma1001-7",
    ("nycu", "110000"): "course-nycu-110000",
    ("nchu", "7386"): "course-nchu-7386",
    ("nchu", "6921"): "course-nchu-6921",
    ("ntust", "AC5004701"): "course-ntust-ac5004701",
    ("ntust", "AC5413701"): "course-ntust-ac5413701",
    ("ntut", "362209"): "course-ntut-362209",
    ("ntut", "361486"): "course-ntut-361486",
    ("niu", "MICRO-001"): "course-niu-freshman-camp",
}


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_name(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.sub(r"(?:教授|副教授|助理教授|講師|老師)$", "", text)
    return re.sub(r"\s+", "", text).strip("、,，;/；")


def official_url(university_id: str, value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES[university_id]):
        raise ValueError(f"non-official URL rejected for {university_id}: {value}")
    return value


def official_university_for_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise ValueError(f"official source must use HTTPS: {value}")
    university_id = next((
        school
        for school, suffixes in ALLOWED_HOST_SUFFIXES.items()
        if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)
    ), None)
    if university_id is None:
        raise ValueError(f"no university policy for official URL: {value}")
    return university_id


def download(filename: str, url: str) -> Path:
    university_id = official_university_for_url(url)
    official_url(university_id, url)
    CACHE.mkdir(exist_ok=True)
    path = CACHE / filename
    if path.exists() and path.stat().st_size > 500:
        return path
    request = urllib.request.Request(url, headers={"User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise FileNotFoundError(url) from error
        raise
    if len(payload) < 500:
        raise ValueError(f"official download is unexpectedly small: {url}")
    path.write_bytes(payload)
    time.sleep(0.15)
    return path


def cached_request(filename: str, url: str, *, data: bytes | None = None,
                   headers: dict[str, str] | None = None, timeout: int = 90,
                   minimum_size: int = 100) -> bytes:
    """Cache a bounded university-owned public response for reproducible imports."""
    official_url(official_university_for_url(url), url)
    CACHE.mkdir(exist_ok=True)
    path = CACHE / filename
    if path.exists() and path.stat().st_size >= minimum_size:
        return path.read_bytes()
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": "WZUNAA-official-course-audit/3.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        **(headers or {}),
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    if len(payload) < minimum_size:
        raise ValueError(f"official response is unexpectedly small: {url}")
    path.write_bytes(payload)
    return payload


def cached_json_request(filename: str, url: str, *, data: bytes | None = None,
                        headers: dict[str, str] | None = None, timeout: int = 90) -> object:
    payload = cached_request(filename, url, data=data, headers=headers, timeout=timeout)
    return json.loads(payload.decode("utf-8-sig"))


def load_active_faculty() -> dict[str, dict[str, dict]]:
    candidates = json.loads((DB / "professor-candidates.generated.json").read_text(encoding="utf-8"))
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in candidates:
        university_id = row["universityId"]
        if university_id not in ALLOWED_HOST_SUFFIXES:
            continue
        source = official_url(university_id, row["sourceUrl"])
        name = normalize_name(row["name"])
        if not name or len(name) < 2:
            continue
        previous = result[university_id].get(name)
        value = {"name": row["name"].strip(), "department": row["department"].strip(), "sourceUrl": source}
        if previous is None or len(source) > len(previous["sourceUrl"]):
            result[university_id][name] = value
    return result


def load_department_sites(university_id: str) -> list[dict]:
    rows = json.loads((DB / "department-sites.generated.json").read_text(encoding="utf-8"))
    return [row for row in rows if row["universityId"] == university_id]


def normalize_department_identity(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.sub(r"(?:碩士|博士|學士)?(?:在職)?(?:專班|班)$", "", text)
    text = re.sub(r"(?:學系|研究所|學位學程|學程|中心|學院|系|所|班)", "", text)
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", text).lower()


_DEPARTMENT_URL_CACHE: dict[tuple[str, str], str] = {}


def department_url(university_id: str, department: str, active_rows: list[dict], department_sites: list[dict]) -> str:
    del active_rows
    cache_key = (university_id, department)
    if cache_key in _DEPARTMENT_URL_CACHE:
        return _DEPARTMENT_URL_CACHE[cache_key]
    target = normalize_department_identity(department)
    ranked = []
    for row in department_sites:
        name = normalize_department_identity(row["name"])
        score = 1000 if row["name"] == department else 900 if name and name == target else 700 if min(len(name), len(target)) >= 2 and (name in target or target in name) else 0
        source = row.get("websiteUrl") or row.get("officialDirectoryUrl")
        if score and source:
            ranked.append((score, len(name), source))
    if ranked:
        result = official_url(university_id, max(ranked)[2])
        _DEPARTMENT_URL_CACHE[cache_key] = result
        return result
    directory = next((row.get("officialDirectoryUrl") for row in department_sites if row.get("officialDirectoryUrl")), None)
    if directory:
        result = official_url(university_id, directory)
        _DEPARTMENT_URL_CACHE[cache_key] = result
        return result
    result = official_url(university_id, COURSE_SOURCE_STATUS[university_id]["officialIndex"])
    _DEPARTMENT_URL_CACHE[cache_key] = result
    return result


def term_from_raw(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 4:
        return None
    year = int(digits[:3])
    semester = digits[3]
    if not EARLIEST_YEAR <= year <= CURRENT_YEAR or semester not in "12":
        return None
    return f"{year}-{semester}"


def split_instructors(value: object) -> list[str]:
    text = str(value or "").replace("\t", "\n")
    raw = re.split(r"[、,，;/／；\n]+", text)
    result = []
    for item in raw:
        name = normalize_name(item)
        if not name or re.search(r"[A-Za-z]", name) or re.search(r"課程|系所|學程|中心|學院|授課|登入|教師", name) or name in {"指導教授", "合授教師", "未定", "待聘", "無"}:
            continue
        if 2 <= len(name) <= 8 and name not in result:
            result.append(name)
    return result


def first_value(row: dict, keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return ""


def iter_nthu_rows(path: Path):
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = data.values() if isinstance(data, dict) else (data,)
        for group in groups:
            if isinstance(group, list):
                yield from group
        return
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        values = sheet.iter_rows(values_only=True)
        try:
            header = [normalize_space(value) for value in next(values)]
        except StopIteration:
            continue
        if "科號" not in header:
            continue
        for cells in values:
            yield dict(zip(header, cells))


def parse_nthu(active: dict[str, dict], report: dict) -> list[dict]:
    parsed = []
    prefix_departments: dict[str, str] = {}
    source_rows = []
    for filename, url in NTHU_SOURCES:
        path = download(filename, url)
        rows = list(iter_nthu_rows(path))
        source_rows.append((url, rows))
        for row in rows:
            code = normalize_space(first_value(row, ("代碼", "開課代碼", "code")))
            department = normalize_space(first_value(row, ("系所全名", "開課單位")))
            if code and department:
                prefix_departments[code] = department
    department_sites = load_department_sites("nthu")

    # The latest university-published schedule is current affiliation evidence.
    # This is materially more complete than relying only on separately crawled
    # faculty profile pages and mirrors the NIU/NCU current-roster rule below.
    for url, rows in source_rows:
        for row in rows:
            raw_code = normalize_space(first_value(row, ("科號",)))
            term = term_from_raw(first_value(row, ("學年期",)) or raw_code[:5])
            if term != f"{CURRENT_YEAR}-1":
                continue
            code = normalize_space(raw_code[5:]) if re.match(r"^\d{5}", raw_code) else raw_code
            prefix = normalize_space(first_value(row, ("代碼", "開課代碼", "code"))) or code.split()[0]
            department = normalize_space(first_value(row, ("系所全名", "開課單位"))) or prefix_departments.get(prefix) or "共同課程"
            for teacher in split_instructors(first_value(row, ("授課教師", "教師"))):
                active.setdefault(teacher, {
                    "name": teacher,
                    "department": department,
                    "sourceUrl": official_url("nthu", url),
                })

    for url, rows in source_rows:
        for row in rows:
            raw_code = normalize_space(first_value(row, ("科號",)))
            term = term_from_raw(first_value(row, ("學年期",)) or raw_code[:5])
            if not term:
                continue
            code = normalize_space(raw_code[5:]) if re.match(r"^\d{5}", raw_code) else raw_code
            name = normalize_space(first_value(row, ("課程中文名稱", "中文課名")))
            teachers = split_instructors(first_value(row, ("授課教師", "教師")))
            active_rows = [active[name] for name in teachers if name in active]
            report["parsedOfferings"] += 1
            if not code or not name or "專題研究" in name or not active_rows:
                report["rejectedWithoutCurrentFaculty"] += 1
                continue
            prefix = normalize_space(first_value(row, ("代碼", "開課代碼", "code"))) or code.split()[0]
            department = normalize_space(first_value(row, ("系所全名", "開課單位"))) or prefix_departments.get(prefix) or active_rows[0]["department"]
            parsed.append({
                "universityId": "nthu", "term": term, "courseCode": code, "name": name,
                "department": department, "officialSourceUrl": official_url("nthu", url),
                "departmentSourceUrl": department_url("nthu", department, active_rows, department_sites),
                "instructors": active_rows,
            })
    return parsed


def nycu_labeled_value(page: str, label: str) -> str:
    match = re.search(
        rf"{re.escape(label)}</div>\s*<div[^>]*>(.*?)</div>",
        page,
        flags=re.I | re.S,
    )
    return strip_html_fragment(match.group(1)) if match else ""


def nycu_course_page(source: str, year: int, semester: int) -> dict | None:
    course_no = urllib.parse.unquote(source.rstrip("/").rsplit("/", 1)[-1])
    cache_token = hashlib.sha256(source.encode()).hexdigest()[:20]
    page = cached_request(
        f"nycu-{year}{semester}-course-{cache_token}.html",
        source,
        timeout=90,
        minimum_size=1_000,
    ).decode("utf-8", "replace")
    structured = None
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        flags=re.I | re.S,
    ):
        try:
            candidate = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("@type") == "Course":
            structured = candidate
            break
    name = normalize_space((structured or {}).get("name"))
    permanent_no = nycu_labeled_value(page, "永久課號")
    department = nycu_labeled_value(page, "開課單位")
    teachers = split_instructors(nycu_labeled_value(page, "授課教師"))
    # A published official page can legitimately have no teacher assigned yet.
    # Count the page as parsed so coverage validation measures fetch/schema
    # failures; the current-faculty filter below still excludes unassigned rows.
    if not course_no or not name:
        return None
    return {
        "courseNo": course_no,
        "permanentNo": permanent_no,
        "nameZh": name,
        "units": [department] if department else [],
        "teachers": teachers,
        "source": source,
    }


def nycu_term_rows(year: int, semester: int) -> tuple[list[dict], int]:
    """Read one NYCU term exclusively from its university-owned sitemap/pages."""
    raw_term = f"{year}{semester}"
    sitemap_url = f"{NYCU_OFFICIAL_SITE}/sitemap/{year}/{semester}.xml?page=1"
    sitemap_payload = cached_request(
        f"nycu-{raw_term}-sitemap.xml", sitemap_url, timeout=90, minimum_size=200,
    )
    root = ET.fromstring(sitemap_payload)
    official_pages = sorted({
        official_url("nycu", (node.text or "").strip())
        for node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        if (node.text or "").strip().startswith(f"{NYCU_OFFICIAL_SITE}/course/{year}/{semester}/")
    })
    if not official_pages:
        raise ValueError(f"NYCU official sitemap is empty for {raw_term}")

    rows: list[dict] = []
    failures = 0

    def fetch(source: str) -> dict | None:
        for attempt in range(3):
            try:
                return nycu_course_page(source, year, semester)
            except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch, source): source for source in official_pages}
        for future in concurrent.futures.as_completed(futures):
            try:
                row = future.result()
                if row:
                    rows.append(row)
                else:
                    failures += 1
            except Exception:
                failures += 1
    if len(rows) < max(1, int(len(official_pages) * 0.95)):
        raise ValueError(
            f"NYCU official page coverage too low for {raw_term}: "
            f"{len(rows)}/{len(official_pages)}"
        )
    return rows, failures


def parse_nycu(active: dict[str, dict], report: dict) -> list[dict]:
    downloaded: list[tuple[int, int, list[dict], int]] = []
    term_pairs = [(CURRENT_YEAR, 1)] + [pair for pair in TERM_PAIRS if pair != (CURRENT_YEAR, 1)]

    def fetch(pair: tuple[int, int]):
        year, semester = pair
        return year, semester, *nycu_term_rows(year, semester)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch, pair): pair for pair in term_pairs}
        for future in concurrent.futures.as_completed(futures):
            year, semester = futures[future]
            term = f"{year}-{semester}"
            try:
                downloaded.append(future.result())
                report["availableTerms"].append(term)
            except Exception as error:
                report["missingTerms"].append(term)
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")

    department_sites = load_department_sites("nycu")
    current = next((item for item in downloaded if item[0:2] == (CURRENT_YEAR, 1)), None)
    if current:
        year, semester, rows, _ = current
        for row in rows:
            course_no = normalize_space(row.get("courseNo"))
            source = normalize_space(row.get("source"))
            if not course_no or not source:
                continue
            department = normalize_space((row.get("units") or [""])[0]) or "共同課程"
            for teacher in split_instructors("、".join(row.get("teachers") or [])):
                active.setdefault(teacher, {
                    "name": teacher,
                    "department": department,
                    "sourceUrl": official_url("nycu", source),
                })

    parsed = []
    for year, semester, rows, failures in sorted(downloaded):
        term = f"{year}-{semester}"
        if failures:
            report.setdefault("pageParseFailures", {})[term] = failures
        for row in rows:
            report["parsedOfferings"] += 1
            course_no = normalize_space(row.get("courseNo"))
            source = normalize_space(row.get("source"))
            name = normalize_space(row.get("nameZh"))
            teachers = split_instructors("、".join(row.get("teachers") or []))
            active_rows = [active[teacher] for teacher in teachers if teacher in active]
            if not course_no or not source or not name or "專題研究" in name or not active_rows:
                report["rejectedWithoutCurrentFaculty"] += 1
                continue
            permanent_no = normalize_space(row.get("permanentNo"))
            code = permanent_no or f"{year}{semester}-{course_no}"
            department = normalize_space((row.get("units") or [""])[0]) or active_rows[0]["department"]
            parsed.append({
                "universityId": "nycu", "term": term, "courseCode": code, "name": name,
                "department": department, "officialSourceUrl": official_url("nycu", source),
                "departmentSourceUrl": department_url("nycu", department, active_rows, department_sites),
                "instructors": active_rows,
            })
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return parsed


def strip_html_fragment(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    return normalize_space(re.sub(r"<[^>]+>", " ", html.unescape(value)))


def nchu_page_rows(page: str, department: str) -> list[dict]:
    rows = []
    # NCHU's public table omits most closing </tr> tags, so a conventional
    # row regex silently collapses an entire department into one record.
    blocks = re.split(r'<tr[^>]*class=["\']trall["\'][^>]*>', page, flags=re.I)[1:]
    for raw_block in blocks:
        block = re.split(
            r'<tr[^>]*class=["\']trall["\']|</tbody>|</table>',
            raw_block,
            maxsplit=1,
            flags=re.I,
        )[0]
        link = re.search(
            r'href=["\']([^"\']*Syllabus_main\?v_strm=(\d+)&(?:amp;)?v_class_nbr=(\d+)[^"\']*)["\'][^>]*>([^<]+)</a>',
            block,
            flags=re.I | re.S,
        )
        course_cell = re.search(
            r'<td[^>]*data-label=["\']科目名稱["\'][^>]*>(.*?)</td>', block, flags=re.I | re.S,
        )
        teacher_cells = re.findall(
            r'<td(?P<attrs>[^>]*)data-label=["\'](?:上課教師|實習教師)["\'][^>]*>(?P<body>.*?)</td>',
            block,
            flags=re.I | re.S,
        )
        if not link or not course_cell or not teacher_cells:
            continue
        name_fragment = re.split(r'<span[^>]*class=["\']mobile-course-number["\']', course_cell.group(1), maxsplit=1, flags=re.I)[0]
        name = strip_html_fragment(name_fragment)
        teachers = []
        for attrs, body in teacher_cells:
            title = re.search(r'title=["\']([^"\']*)["\']', attrs, flags=re.I)
            teacher_text = html.unescape(title.group(1)) if title else strip_html_fragment(body)
            for teacher in split_instructors(teacher_text.removesuffix("等")):
                if teacher not in teachers:
                    teachers.append(teacher)
        code = normalize_space(strip_html_fragment(link.group(4)))
        department_cell = re.search(
            r'<td[^>]*data-label=["\']開課單位["\'][^>]*>(.*?)</td>',
            block,
            flags=re.I | re.S,
        )
        row_department = strip_html_fragment(department_cell.group(1)) if department_cell else department
        if not name or not code or not teachers or "專題研究" in name:
            continue
        source = urljoin("https://onepiece.nchu.edu.tw/cofsys/plsql/", html.unescape(link.group(1)))
        rows.append({
            "term": f"{link.group(2)[:3]}-{link.group(2)[3]}",
            "courseCode": code,
            "name": name,
            "department": row_department or department,
            "teachers": teachers,
            "officialSourceUrl": source,
        })
    return rows


def parse_nchu(active: dict[str, dict], report: dict) -> list[dict]:
    raw_term = f"{CURRENT_YEAR}1"
    base = "https://onepiece.nchu.edu.tw/cofsys/plsql/"
    home = cached_request(
        f"nchu-{raw_term}-home.html", base + "crseqry_home2", timeout=60, minimum_size=500,
    ).decode("utf-8", "replace")
    token_match = re.search(rf'<option[^>]*value=["\']([^"\']+)["\'][^>]*>{raw_term}</option>', home, flags=re.I)
    if not token_match:
        raise RuntimeError("NCHU current-term token is unavailable")
    year_token = token_match.group(1)
    jobs: list[tuple[str, str, str]] = []
    for career in ("U", "G", "D", "R", "W", "N"):
        body = urllib.parse.urlencode({"v_year": year_token, "v_career": career, "v_excel": "0"}).encode()
        page = cached_request(
            f"nchu-{raw_term}-{career}-departments.html",
            base + "crseqry_home2_now",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
            minimum_size=500,
        ).decode("utf-8", "replace")
        for code, label in re.findall(r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>([^<]+)</option>', page, flags=re.I):
            label = normalize_space(html.unescape(label))
            if not code.startswith(career) or label == career:
                continue
            department = normalize_space(re.sub(rf"^{re.escape(code)}\s*", "", label))
            if department:
                jobs.append((career, code, department))

    def fetch(job: tuple[str, str, str]) -> tuple[str, str, str | None]:
        career, code, department = job
        body = urllib.parse.urlencode({
            "v_year": year_token, "v_career": career, "v_dept": code, "v_level": "",
            "v_text": "", "v_teach": "", "v_week": "", "v_mtg": "", "v_lang": "",
            "v_excel": "0", "v_emi": "",
        }).encode()
        try:
            payload = cached_request(
                f"nchu-{raw_term}-{career}-{code}.html",
                base + "crseqry_home2_now",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=90,
                minimum_size=500,
            )
            return payload.decode("utf-8", "replace"), department, None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as error:
            return "", department, type(error).__name__

    source_rows = []
    failed_queries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for page, department, error_name in executor.map(fetch, jobs):
            if error_name:
                failed_queries.append({"department": department, "error": error_name})
                continue
            source_rows.extend(nchu_page_rows(page, department))

    department_sites = load_department_sites("nchu")
    for row in source_rows:
        for teacher in row["teachers"]:
            active.setdefault(teacher, {
                "name": teacher,
                "department": row["department"],
                "sourceUrl": official_url("nchu", row["officialSourceUrl"]),
            })

    parsed = []
    for row in source_rows:
        report["parsedOfferings"] += 1
        active_rows = [active[teacher] for teacher in row["teachers"] if teacher in active]
        if not active_rows:
            report["rejectedWithoutCurrentFaculty"] += 1
            continue
        parsed.append({
            "universityId": "nchu", "term": row["term"], "courseCode": row["courseCode"],
            "name": row["name"], "department": row["department"],
            "officialSourceUrl": official_url("nchu", row["officialSourceUrl"]),
            "departmentSourceUrl": department_url("nchu", row["department"], active_rows, department_sites),
            "instructors": active_rows,
        })
    report["availableTerms"] = [f"{CURRENT_YEAR}-1"]
    report["missingTerms"] = [f"{year}-{semester}" for year, semester in TERM_PAIRS if (year, semester) != (CURRENT_YEAR, 1)]
    report["officialDepartmentQueries"] = len(jobs)
    report["failedDepartmentQueries"] = failed_queries
    return parsed


def ntust_department_map() -> dict[str, str]:
    colleges = cached_json_request(
        "ntust-1151-colleges.json", f"{NTUST_API}/Colleges/1151", timeout=60,
    )
    mapping: dict[str, str] = {}
    for college in colleges if isinstance(colleges, list) else []:
        college_no = normalize_space(college.get("CollegeNo"))
        if not college_no:
            continue
        departments = cached_json_request(
            f"ntust-1151-departments-{college_no}.json",
            f"{NTUST_API}/departments?collegeNo={urllib.parse.quote(college_no)}",
            timeout=60,
        )
        for row in departments if isinstance(departments, list) else []:
            code = normalize_space(row.get("DeptNo"))
            name = normalize_space(row.get("Department"))
            if code and name:
                mapping[code] = name
    return mapping


def ntust_query(term: str) -> list[dict]:
    payload = {
        "Semester": term, "CourseNo": "", "CourseName": "", "CourseTeacher": "",
        "Dimension": "", "CourseNotes": "", "CampusNotes": "", "ForeignLanguage": 0,
        "OnlyIntensive": 0, "OnlyGeneral": 0, "OnleyNTUST": 1,
        "OnlyMaster": 0, "OnlyUnderGraduate": 0, "OnlyNode": 1, "Language": "zh",
    }
    result = cached_json_request(
        f"ntust-{term}-courses.json", f"{NTUST_API}/courses",
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "Referer": "https://querycourse.ntust.edu.tw/querycourse/"},
        timeout=180,
    )
    return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []


def parse_ntust(active: dict[str, dict], report: dict) -> list[dict]:
    department_codes = ntust_department_map()
    downloaded: list[tuple[str, list[dict]]] = []
    raw_terms = [f"{CURRENT_YEAR}1"] + [f"{year}{semester}" for year, semester in TERM_PAIRS if (year, semester) != (CURRENT_YEAR, 1)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(ntust_query, term): term for term in raw_terms}
        for future in concurrent.futures.as_completed(futures):
            raw_term = futures[future]
            term = f"{raw_term[:3]}-{raw_term[3]}"
            try:
                rows = future.result()
                if not rows:
                    raise ValueError("empty official course response")
                downloaded.append((raw_term, rows))
                report["availableTerms"].append(term)
            except Exception as error:
                report["missingTerms"].append(term)
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")

    def resolve_department(course_no: str, fallback: str = "") -> str:
        matches = [(len(code), name) for code, name in department_codes.items() if course_no.startswith(code)]
        return max(matches)[1] if matches else fallback or "共同課程"

    current = next((rows for term, rows in downloaded if term == f"{CURRENT_YEAR}1"), [])
    for row in current:
        course_no = normalize_space(row.get("CourseNo"))
        department = resolve_department(course_no)
        source = f"https://querycourse.ntust.edu.tw/QueryCourse/?CourseNo={urllib.parse.quote(course_no)}&Semester={CURRENT_YEAR}1"
        for teacher in split_instructors(row.get("CourseTeacher")):
            active.setdefault(teacher, {
                "name": teacher,
                "department": department,
                "sourceUrl": official_url("ntust", source),
            })

    department_sites = load_department_sites("ntust")
    parsed = []
    for raw_term, rows in sorted(downloaded):
        term = f"{raw_term[:3]}-{raw_term[3]}"
        for row in rows:
            report["parsedOfferings"] += 1
            course_no = normalize_space(row.get("CourseNo"))
            name = normalize_space(row.get("CourseName"))
            teachers = split_instructors(row.get("CourseTeacher"))
            active_rows = [active[teacher] for teacher in teachers if teacher in active]
            if not course_no or not name or "專題研究" in name or not active_rows:
                report["rejectedWithoutCurrentFaculty"] += 1
                continue
            department = resolve_department(course_no, active_rows[0]["department"])
            source = f"https://querycourse.ntust.edu.tw/QueryCourse/?CourseNo={urllib.parse.quote(course_no)}&Semester={raw_term}"
            parsed.append({
                "universityId": "ntust", "term": term, "courseCode": course_no, "name": name,
                "department": department, "officialSourceUrl": official_url("ntust", source),
                "departmentSourceUrl": department_url("ntust", department, active_rows, department_sites),
                "instructors": active_rows,
            })
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return parsed


class NcuFetcher:
    def __init__(self):
        self.local = threading.local()

    def opener(self):
        if not getattr(self.local, "opener", None):
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            request = urllib.request.Request("https://cis.ncu.edu.tw/Course/main/lang", headers={"User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)"})
            opener.open(request, timeout=45).read()
            self.local.opener = opener
        return self.local.opener

    def fetch(self, url: str, cache_name: str) -> str:
        official_url("ncu", url)
        CACHE.mkdir(exist_ok=True)
        path = CACHE / cache_name
        if path.exists() and path.stat().st_size > 500:
            return path.read_text(encoding="utf-8", errors="replace")
        last_error = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)"})
                payload = self.opener().open(request, timeout=45).read()
                text = payload.decode("utf-8", "replace")
                if len(text) < 500:
                    raise ValueError(f"NCU response too small: {url}")
                path.write_text(text, encoding="utf-8")
                time.sleep(0.05)
                return text
            except Exception as error:
                last_error = error
                self.local.opener = None
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"NCU fetch failed: {url}") from last_error


def ncu_page_courses(page: str, term: str, fallback_department: str, active: dict[str, dict], department_sites: list[dict], report: dict) -> list[dict]:
    parser = TableParser()
    parser.feed(page)
    heading = re.search(r"<h5>[^：:]*[：:]?\s*\d{4}\s*\|\s*([^<(]+)", page, flags=re.I)
    department = normalize_space(heading.group(1)) if heading else fallback_department
    parsed = []
    for row in parser.rows:
        if len(row) < 10 or "課程代碼" in row[0][0] or "Course Code" in row[0][0]:
            continue
        identity_parts = [part.strip() for part in row[0][0].split("／") if part.strip()]
        if len(identity_parts) < 2 or not identity_parts[0].isdigit():
            continue
        serial, code = identity_parts[0], identity_parts[1]
        name = normalize_space(row[1][0].split("／", 1)[0])
        teachers = split_instructors(row[2][0])
        source = f"https://cis.ncu.edu.tw/Course/main/query/byKeywords?serialNo={serial}&outline={serial}&semester={term.replace('-', '')}"
        if term == "115-1":
            for teacher in teachers:
                if teacher not in active:
                    active[teacher] = {"name": teacher, "department": department or fallback_department, "sourceUrl": source}
        active_rows = [active[teacher] for teacher in teachers if teacher in active]
        report["parsedOfferings"] += 1
        if not code or not name or not active_rows:
            report["rejectedWithoutCurrentFaculty"] += 1
            continue
        actual_department = department or active_rows[0]["department"]
        parsed.append({
            "universityId": "ncu", "term": term, "courseCode": code, "name": name,
            "department": actual_department, "officialSourceUrl": official_url("ncu", source),
            "departmentSourceUrl": department_url("ncu", actual_department, active_rows, department_sites),
            "instructors": active_rows,
        })
    return parsed


def parse_ncu(active: dict[str, dict], report: dict) -> list[dict]:
    fetcher = NcuFetcher()
    department_sites = load_department_sites("ncu")
    all_rows = []
    available_terms = []
    term_pairs = [(CURRENT_YEAR, 1)] + [pair for pair in TERM_PAIRS if pair != (CURRENT_YEAR, 1)]
    for year, semester in term_pairs:
        raw_term = f"{year}{semester}"
        term = f"{year}-{semester}"
        dept_url = f"https://cis.ncu.edu.tw/Course/main/query/byYears?do=showDept&semester={raw_term}"
        try:
            dept_page = fetcher.fetch(dept_url, f"ncu-{raw_term}-departments.html")
        except RuntimeError:
            report["missingTerms"].append(term)
            continue
        matches = re.findall(r'href="([^"]*do=showList[^"]*)"', dept_page, flags=re.I)
        links = []
        for href in matches:
            clean = html.unescape(href).replace(";jsessionid=", ";ignored=")
            clean = re.sub(r";ignored=[^?]+", "", clean)
            url = urljoin("https://cis.ncu.edu.tw/", clean)
            if url not in links:
                links.append(url)
        if not links:
            report["missingTerms"].append(term)
            continue

        def fetch_department(url: str):
            key = hashlib.sha256(url.encode()).hexdigest()[:12]
            first_page = fetcher.fetch(url, f"ncu-{raw_term}-{key}-1.html")
            pages = [first_page]
            page_keys = re.findall(r"[?&](d-[^=]+-p)=(\d+)", html.unescape(first_page))
            max_page = max((int(number) for _, number in page_keys), default=1)
            page_key = page_keys[0][0] if page_keys else "d-49489-p"
            for page_number in range(2, max_page + 1):
                separator = "&" if "?" in url else "?"
                page_url = f"{url}{separator}{page_key}={page_number}"
                pages.append(fetcher.fetch(page_url, f"ncu-{raw_term}-{key}-{page_number}.html"))
            return pages

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_department, url) for url in links]
            for future in concurrent.futures.as_completed(futures):
                try:
                    pages = future.result()
                except Exception:
                    report.setdefault("fetchErrors", 0)
                    report["fetchErrors"] += 1
                    continue
                for page in pages:
                    all_rows.extend(ncu_page_courses(page, term, "", active, department_sites, report))
        available_terms.append(term)
        print(f"NCU {raw_term}: {len(all_rows)} verified offerings", flush=True)
    report["availableTerms"] = sorted(available_terms)
    return all_rows


class StaticOfficialFetcher:
    def fetch(self, university_id: str, url: str, cache_name: str) -> str:
        official_url(university_id, url)
        CACHE.mkdir(exist_ok=True)
        path = CACHE / cache_name
        if path.exists() and path.stat().st_size > 500:
            return path.read_text(encoding="utf-8", errors="replace")
        last_error = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)"})
                payload = urllib.request.urlopen(request, timeout=45).read()
                text = payload.decode("utf-8", "replace")
                if len(text) < 500:
                    raise ValueError(f"official response too small: {url}")
                path.write_text(text, encoding="utf-8")
                time.sleep(0.05)
                return text
            except Exception as error:
                last_error = error
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"official fetch failed: {url}") from last_error


def ntu_page_courses(page: str, term: str, active: dict[str, dict], department_sites: list[dict], report: dict) -> list[dict]:
    parser = TableParser()
    parser.feed(page)
    parsed = []
    for row in parser.rows:
        if len(row) < 12 or not row[2][0] or row[2][0] == "課號":
            continue
        code = normalize_space(row[2][0])
        name = normalize_space(row[4][0])
        if not re.search(r"\d", code):
            continue
        teachers = split_instructors(row[10][0])
        if not teachers:
            continue
        source_link = row[4][1][0] if row[4][1] else ""
        source = urljoin("https://nol.ntu.edu.tw/nol/coursesearch/", source_link)
        if term == "115-1" and source_link:
            for teacher in teachers:
                if teacher not in active:
                    active[teacher] = {"name": teacher, "department": "共同課程", "sourceUrl": source}
        active_rows = [active[teacher] for teacher in teachers if teacher in active]
        report["parsedOfferings"] += 1
        if not code or not name or not source_link or not active_rows:
            report["rejectedWithoutCurrentFaculty"] += 1
            continue
        department = active_rows[0]["department"]
        parsed.append({
            "universityId": "ntu", "term": term, "courseCode": code, "name": name,
            "department": department, "officialSourceUrl": official_url("ntu", source),
            "departmentSourceUrl": department_url("ntu", department, active_rows, department_sites),
            "instructors": active_rows,
        })
    return parsed


def parse_ntu(active: dict[str, dict], report: dict) -> list[dict]:
    fetcher = StaticOfficialFetcher()
    department_sites = load_department_sites("ntu")
    all_rows = []
    available_terms = []
    term_pairs = [(CURRENT_YEAR, 1)] + [pair for pair in TERM_PAIRS if pair != (CURRENT_YEAR, 1)]
    for year, semester in term_pairs:
        term = f"{year}-{semester}"

        def page_url(offset: int) -> str:
            return (
                "https://nol.ntu.edu.tw/nol/coursesearch/search_for_02_dpt.php?"
                f"current_sem={term}&dptname=0&coursename=&teachername=&alltime=yes&"
                f"allproced=yes&allsel=yes&yearcode=0&page_cnt=150&startrec={offset}"
            )

        try:
            first_page = fetcher.fetch("ntu", page_url(0), f"ntu-{year}{semester}-0.html")
        except RuntimeError:
            report["missingTerms"].append(term)
            continue
        count_match = re.search(r"共查詢到\s*<font[^>]*>\s*<b>(\d+)</b>", first_page)
        total = int(count_match.group(1)) if count_match else 0
        if total <= 0:
            report["missingTerms"].append(term)
            continue
        pages = [first_page]
        offsets = list(range(150, total, 150))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(fetcher.fetch, "ntu", page_url(offset), f"ntu-{year}{semester}-{offset}.html"): offset
                for offset in offsets
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    pages.append(future.result())
                except Exception:
                    report.setdefault("fetchErrors", 0)
                    report["fetchErrors"] += 1
        for page in pages:
            all_rows.extend(ntu_page_courses(page, term, active, department_sites, report))
        available_terms.append(term)
        print(f"NTU {year}{semester}: {len(all_rows)} verified offerings", flush=True)
    report["availableTerms"] = sorted(available_terms)
    return all_rows


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[tuple[str, list[str]]]] = []
        self.current_row: list[tuple[str, list[str]]] | None = None
        self.current_cell: list[str] | None = None
        self.current_links: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            if self.current_row:
                if self.current_cell is not None:
                    self.current_row.append((normalize_space("".join(self.current_cell)), self.current_links[:]))
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag in {"td", "th"} and self.current_row is not None:
            if self.current_cell is not None:
                self.current_row.append((normalize_space("".join(self.current_cell)), self.current_links[:]))
            self.current_cell = []
            self.current_links = []
        elif tag == "a" and self.current_cell is not None:
            href = dict(attrs).get("href")
            if href:
                self.current_links.append(href)
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.append("／")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_row.append((normalize_space("".join(self.current_cell)), self.current_links[:]))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = None


def parse_ccu(active: dict[str, dict], report: dict) -> list[dict]:
    parsed = []
    department_sites = load_department_sites("ccu")
    available_terms = []
    for raw_term in CCU_TERMS:
        url = f"https://kiki.ccu.edu.tw/~ccmisp06/Course/zipfiles/{raw_term}.tgz"
        try:
            path = download(f"ccu-{raw_term}.tgz", url)
        except FileNotFoundError:
            report["missingTerms"].append(f"{raw_term[:3]}-{raw_term[3]}")
            continue
        available_terms.append(f"{raw_term[:3]}-{raw_term[3]}")
        with tarfile.open(path, "r:gz") as archive:
            names = [name for name in archive.getnames() if name.endswith(".html") and not name.endswith("_e.html")]
            for filename in names:
                member = archive.extractfile(filename)
                if member is None:
                    continue
                page = member.read().decode("utf-8", "replace")
                department_match = re.search(r"系所別:\s*([^<]+)", page)
                department = normalize_space(department_match.group(1)) if department_match else filename.rsplit(".", 1)[0]
                table = TableParser()
                table.feed(page)
                for row in table.rows:
                    if len(row) < 12 or row[0][0] in {"年級", ""}:
                        continue
                    code = normalize_space(row[1][0] + (f"-{row[2][0]}" if row[2][0] else ""))
                    name = normalize_space(row[3][0])
                    teachers = split_instructors(row[4][0])
                    active_rows = [active[name] for name in teachers if name in active]
                    report["parsedOfferings"] += 1
                    if not code or not name or not active_rows:
                        report["rejectedWithoutCurrentFaculty"] += 1
                        continue
                    syllabus_links = row[11][1]
                    source_url = urljoin("https://kiki.ccu.edu.tw/", syllabus_links[0]) if syllabus_links else url
                    if source_url.startswith("http://"):
                        source_url = "https://" + source_url[7:]
                    parsed.append({
                        "universityId": "ccu", "term": f"{raw_term[:3]}-{raw_term[3]}",
                        "courseCode": code, "name": name, "department": department,
                        "officialSourceUrl": official_url("ccu", source_url),
                        "departmentSourceUrl": department_url("ccu", department, active_rows, department_sites),
                        "instructors": active_rows,
                    })
        print(f"CCU {raw_term}: {len(parsed)} verified offerings", flush=True)
    report["availableTerms"] = available_terms
    return parsed


class NtutFetcher:
    def __init__(self):
        self.local = threading.local()

    def opener(self):
        if not getattr(self.local, "opener", None):
            jar = http.cookiejar.CookieJar()
            context = ssl._create_unverified_context()
            self.local.opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(jar),
                urllib.request.HTTPSHandler(context=context),
            )
        return self.local.opener

    def fetch(self, year: int, semester: int, unit: str) -> str:
        CACHE.mkdir(exist_ok=True)
        path = CACHE / f"ntut-{year}{semester}-{unit}.html"
        if path.exists() and path.stat().st_size > 500:
            return path.read_text(encoding="utf-8", errors="replace")
        url = official_url("ntut", "https://aps.ntut.edu.tw/course/tw/QueryCourse.jsp")
        form = urllib.parse.urlencode({
            "stime": "0", "year": str(year), "sem": str(semester),
            "matric": "'0','1','4','5','6','7','8','9','A','C','D','E','F'",
            "unit": unit, "cname": "", "ccode": "", "tname": "",
        }).encode()
        last_error = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, data=form, headers={"User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)"})
                payload = self.opener().open(request, timeout=45).read()
                text = payload.decode("utf-8", "replace")
                if len(text) < 500:
                    raise ValueError(f"NTUT response too small: {year}-{semester} {unit}")
                path.write_text(text, encoding="utf-8")
                time.sleep(0.05)
                return text
            except Exception as error:
                last_error = error
                self.local.opener = None
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"NTUT fetch failed: {year}-{semester} {unit}") from last_error


def ntut_page_courses(page: str, term: str, department: str, active: dict[str, dict], department_sites: list[dict], report: dict) -> list[dict]:
    parser = TableParser()
    parser.feed(page)
    parsed = []
    for row in parser.rows:
        if len(row) < 20 or row[0][0] in {"課號", ""}:
            continue
        course_links = row[1][1]
        code_match = re.search(r"[?&]code=([^&]+)", course_links[0] if course_links else "")
        code = normalize_space(code_match.group(1) if code_match else "")
        name = normalize_space(row[1][0].split("／", 1)[0])
        teachers = split_instructors(row[7][0])
        syllabus_links = row[19][1]
        source = urljoin("https://aps.ntut.edu.tw/course/tw/", syllabus_links[0] if syllabus_links else (course_links[0] if course_links else "QueryCurrPage.jsp"))
        if term == "115-1":
            for teacher in teachers:
                if teacher not in active:
                    active[teacher] = {"name": teacher, "department": department, "sourceUrl": source + "#semester=115-1"}
        active_rows = [active[teacher] for teacher in teachers if teacher in active]
        report["parsedOfferings"] += 1
        if not code or not name or not active_rows:
            report["rejectedWithoutCurrentFaculty"] += 1
            continue
        parsed.append({
            "universityId": "ntut", "term": term, "courseCode": code, "name": name,
            "department": department or active_rows[0]["department"],
            "officialSourceUrl": official_url("ntut", source),
            "departmentSourceUrl": department_url("ntut", department, active_rows, department_sites),
            "instructors": active_rows,
        })
    return parsed


def parse_ntut(active: dict[str, dict], report: dict) -> list[dict]:
    index_path = download("ntut-course-index.html", "https://aps.ntut.edu.tw/course/tw/QueryCurrPage.jsp")
    index_page = index_path.read_text(encoding="utf-8", errors="replace")
    unit_match = re.search(r'<select[^>]+name="?unit"?[^>]*>(.*?)</select>', index_page, flags=re.I | re.S)
    if not unit_match:
        report["missingTerms"].append("unit-index")
        return []
    units = []
    for value, label in re.findall(r'<option\s+value="([^"]+)"[^>]*>([^<]+)</option>', unit_match.group(1), flags=re.I):
        name = normalize_space(label)
        if value != "＊" and (value, name) not in units:
            units.append((value, re.sub(r"^[A-Z0-9]+\s*", "", name)))

    fetcher = NtutFetcher()
    department_sites = load_department_sites("ntut")
    parsed = []
    available_terms = []
    term_pairs = [(CURRENT_YEAR, 1)] + [pair for pair in TERM_PAIRS if pair != (CURRENT_YEAR, 1)]
    for year, semester in term_pairs:
        term = f"{year}-{semester}"
        term_rows = []

        def fetch_unit(item):
            unit, department = item
            return department, fetcher.fetch(year, semester, unit)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_unit, item) for item in units]
            for future in concurrent.futures.as_completed(futures):
                try:
                    department, page = future.result()
                    term_rows.extend(ntut_page_courses(page, term, department, active, department_sites, report))
                except Exception:
                    report.setdefault("fetchErrors", 0)
                    report["fetchErrors"] += 1
        if term_rows:
            available_terms.append(term)
            parsed.extend(term_rows)
        else:
            report["missingTerms"].append(term)
        print(f"NTUT {year}{semester}: {len(parsed)} verified offerings", flush=True)
    report["availableTerms"] = sorted(available_terms)
    return parsed


class NiuFormParser(HTMLParser):
    """Collect enough ASP.NET form state to request NIU's public Excel export."""

    def __init__(self):
        super().__init__()
        self.inputs: list[dict[str, str]] = []
        self.selects: dict[str, list[dict[str, object]]] = {}
        self.current_select: str | None = None
        self.current_option: dict[str, object] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input":
            self.inputs.append(attributes)
        elif tag == "select":
            self.current_select = attributes.get("name")
            if self.current_select:
                self.selects[self.current_select] = []
        elif tag == "option" and self.current_select:
            self.current_option = {"attrs": attributes, "text": []}
            self.selects[self.current_select].append(self.current_option)

    def handle_data(self, data):
        if self.current_option is not None:
            self.current_option["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "option":
            self.current_option = None
        elif tag == "select":
            self.current_select = None

    def parameters(self) -> dict[str, str]:
        result = {}
        for attrs in self.inputs:
            name = attrs.get("name")
            if name and attrs.get("type", "text").lower() in {"hidden", "text"}:
                result[name] = attrs.get("value", "")
        for name, options in self.selects.items():
            selected = next((option for option in options if "selected" in option["attrs"]), None)
            selected = selected or (options[0] if options else None)
            result[name] = str(selected["attrs"].get("value", "")) if selected else ""
        return result

    def programs(self) -> dict[str, str]:
        result = {}
        for option in self.selects.get("Q_FACULTY_CODE", []):
            code = normalize_space(option["attrs"].get("value", ""))
            label = normalize_space("".join(option["text"]))
            if code and label:
                result[code] = re.sub(rf"^{re.escape(code)}\s*[-－]\s*", "", label)
        return result


def niu_term_urls(year: int, semester: int) -> tuple[str, str]:
    raw_term = f"{year}{semester}"
    path = f"/Application/TKE/TKE50/TKE5010_01.aspx?ayearsms={raw_term}"
    encoded = base64.b64encode(path.encode("utf-16le")).decode("ascii")
    outside = official_url("niu", f"https://acade.niu.edu.tw/NIU/outside.aspx?mainPage={encoded}")
    main = official_url("niu", f"https://acade.niu.edu.tw/NIU{path}")
    return outside, main


class NiuCourseFetcher:
    def fetch(self, year: int, semester: int) -> tuple[bytes, dict[str, str], str]:
        CACHE.mkdir(exist_ok=True)
        raw_term = f"{year}{semester}"
        workbook_path = CACHE / f"niu-{raw_term}.xls"
        programs_path = CACHE / f"niu-{raw_term}-programs.json"
        outside, main = niu_term_urls(year, semester)
        if workbook_path.exists() and workbook_path.stat().st_size > 500 and programs_path.exists():
            programs = json.loads(programs_path.read_text(encoding="utf-8"))
            return workbook_path.read_bytes(), programs, outside

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        )
        opener.addheaders = [("User-Agent", "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)")]
        opener.open(outside, timeout=45).read()
        page_request = urllib.request.Request(main, headers={"Referer": outside})
        page = opener.open(page_request, timeout=45).read().decode("utf-8", "replace")
        parser = NiuFormParser()
        parser.feed(page)
        parameters = parser.parameters()
        parameters.update({
            "__EVENTTARGET": "DoExport",
            "__EVENTARGUMENT": "",
            "TYPE": "EXPORT_ALL",
            "OP": "OP1",
            "Q_FACULTY_CODE": "",
            "Q_GRADE": "",
            "Q_MUST": "",
        })
        export_request = urllib.request.Request(
            main,
            data=urllib.parse.urlencode(parameters).encode(),
            headers={"Referer": main, "Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = opener.open(export_request, timeout=90).read()
        if len(payload) < 500 or not payload.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError(f"NIU official export is not an Excel workbook: {raw_term}")
        programs = parser.programs()
        workbook_path.write_bytes(payload)
        programs_path.write_text(json.dumps(programs, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.1)
        return payload, programs, outside


def niu_department(course_code: str, class_name: str, programs: dict[str, str]) -> str:
    compact_code = re.sub(r"\s+", "", course_code).upper()
    candidates = []
    if len(compact_code) >= 4:
        candidates.extend((compact_code[0] + compact_code[2:4], compact_code[2:4]))
    class_codes = re.findall(r"(?:^|,)\s*([A-Z][A-Z0-9]{1,4})\s*-", class_name.upper())
    candidates.extend(class_codes)
    for code in candidates:
        if code in programs:
            return programs[code]
    first_class = normalize_space(class_name.split(",", 1)[0])
    fallback = re.sub(r"^[A-Z][A-Z0-9]{1,4}\s*[-－]\s*", "", first_class)
    fallback = re.sub(r"\s*[1-9](?:甲|乙)?\s*$", "", fallback)
    return fallback or "共同課程"


def niu_workbook_rows(payload: bytes, programs: dict[str, str], term: str, source_url: str) -> list[dict]:
    try:
        import xlrd
    except ImportError as error:
        raise RuntimeError("NIU import requires xlrd; install requirements-course-import.txt") from error

    workbook = xlrd.open_workbook(file_contents=payload)
    raw_rows = []
    for sheet in workbook.sheets():
        for index in range(2, sheet.nrows):
            cells = sheet.row_values(index)
            if len(cells) < 10:
                continue
            class_name = normalize_space(cells[0])
            code = normalize_space(cells[1])
            name = normalize_space(cells[2])
            teachers = split_instructors(cells[9])
            if not code or not name or not teachers or "專題研究" in name:
                continue
            raw_rows.append({
                "term": term,
                "courseCode": code,
                "name": name,
                "department": niu_department(code, class_name, programs),
                "teachers": teachers,
                "officialSourceUrl": source_url,
            })
    return raw_rows


def parse_niu(active: dict[str, dict], report: dict) -> list[dict]:
    fetcher = NiuCourseFetcher()
    downloaded = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetcher.fetch, year, semester): (year, semester)
            for year, semester in TERM_PAIRS
        }
        for future in concurrent.futures.as_completed(futures):
            year, semester = futures[future]
            term = f"{year}-{semester}"
            try:
                payload, programs, source_url = future.result()
                downloaded.append((term, payload, programs, source_url))
            except Exception:
                report["missingTerms"].append(term)
                report.setdefault("fetchErrors", 0)
                report["fetchErrors"] += 1

    source_rows = []
    for term, payload, programs, source_url in sorted(downloaded):
        term_rows = niu_workbook_rows(payload, programs, term, source_url)
        source_rows.extend(term_rows)
        report["availableTerms"].append(term)
        print(f"NIU {term}: {len(term_rows)} official offerings", flush=True)

    department_sites = load_department_sites("niu")
    # A teacher appearing in the university's published 115-1 schedule is current
    # official evidence even when a separate faculty profile was not discovered.
    for row in source_rows:
        if row["term"] != f"{CURRENT_YEAR}-1":
            continue
        for teacher in row["teachers"]:
            active.setdefault(teacher, {
                "name": teacher,
                "department": row["department"],
                "sourceUrl": row["officialSourceUrl"],
            })

    parsed = []
    for row in source_rows:
        report["parsedOfferings"] += 1
        active_rows = [active[teacher] for teacher in row["teachers"] if teacher in active]
        if not active_rows:
            report["rejectedWithoutCurrentFaculty"] += 1
            continue
        for instructor in active_rows:
            teacher_token = hashlib.sha256(instructor["name"].encode()).hexdigest()[:8]
            parsed.append({
                "universityId": "niu",
                "term": row["term"],
                "courseCode": f"{row['courseCode']}-{teacher_token}",
                "name": row["name"],
                "department": row["department"],
                "officialSourceUrl": official_url("niu", row["officialSourceUrl"]),
                "departmentSourceUrl": department_url("niu", row["department"], [instructor], department_sites),
                "instructors": [instructor],
            })
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return parsed


def current_verified_fallbacks() -> list[dict]:
    """Keep verified 115-1 official records where history endpoints are restricted.

    A current official syllabus or course file is itself current-affiliation
    evidence. These records avoid replacing useful official data with an empty
    school while a compliant historical adapter remains unavailable.
    """
    seeds = [
        {
            "universityId": "nycu", "term": "115-1", "courseCode": "110000", "name": "行醫醫定行", "department": "醫學系",
            "officialSourceUrl": "https://coz.aa.nycu.edu.tw/course/115/1/110000", "departmentSourceUrl": "https://med.nycu.edu.tw/",
            "instructorNames": ["楊智傑", "張原翊", "凌憬峯", "阮琪昌"],
        },
        {
            "universityId": "nchu", "term": "115-1", "courseCode": "7386", "name": "電子研討（二）", "department": "電機工程學系",
            "officialSourceUrl": "https://onepiece.nchu.edu.tw/cofsys/plsql/Syllabus?v_class_nbr=6091&v_strm=1151", "departmentSourceUrl": "https://www.ee.nchu.edu.tw/",
            "instructorNames": ["賴聰賢"],
        },
        {
            "universityId": "nchu", "term": "115-1", "courseCode": "6921", "name": "生物與永續科技專題討論（一）", "department": "永續農業與綠色科技學位學程",
            "officialSourceUrl": "https://onepiece.nchu.edu.tw/cofsys/plsql/Syllabus?v_class_nbr=5507&v_strm=1151", "departmentSourceUrl": "https://bpbiot.nchu.edu.tw/",
            "instructorNames": ["顏佩翎"],
        },
        {
            "universityId": "ntust", "term": "115-1", "courseCode": "AC5004701", "name": "電腦輔助設計／製造理論及實務", "department": "自動化及控制研究所",
            "officialSourceUrl": "https://querycourse.ntust.edu.tw/QueryCourse/?CourseNo=AC5004701&Semester=1151", "departmentSourceUrl": "https://www.ac.ntust.edu.tw/",
            "instructorNames": ["賴嘉宏"],
        },
        {
            "universityId": "ntust", "term": "115-1", "courseCode": "AC5413701", "name": "型樣識別與機器學習", "department": "自動化及控制研究所",
            "officialSourceUrl": "https://querycourse.ntust.edu.tw/QueryCourse/?CourseNo=AC5413701&Semester=1151", "departmentSourceUrl": "https://www.ac.ntust.edu.tw/",
            "instructorNames": ["顏志達"],
        },
    ]
    result = []
    for seed in seeds:
        university_id = seed["universityId"]
        source = official_url(university_id, seed["officialSourceUrl"])
        result.append({
            **{key: value for key, value in seed.items() if key != "instructorNames"},
            "officialSourceUrl": source,
            "departmentSourceUrl": official_url(university_id, seed["departmentSourceUrl"]),
            "instructors": [
                {"name": name, "department": seed["department"], "sourceUrl": source}
                for name in seed["instructorNames"]
            ],
        })
    return result


def course_id(row: dict) -> str:
    legacy_id = LEGACY_COURSE_IDS.get((row["universityId"], row["courseCode"]))
    if legacy_id:
        return legacy_id
    identity = "\0".join((row["universityId"], row["courseCode"]))
    return "course-" + row["universityId"] + "-" + hashlib.sha256(identity.encode()).hexdigest()[:16]


def deduplicate(rows: list[dict]) -> list[dict]:
    merged = {}
    for row in rows:
        if "專題研究" in normalize_space(row.get("name")):
            continue
        key = (row["universityId"], row["courseCode"])
        current = merged.get(key)
        if current is None:
            current = {**row, "instructors": [], "offeredTerms": set()}
            merged[key] = current
        elif row["term"] > current["term"]:
            for field in ("term", "name", "department", "officialSourceUrl", "departmentSourceUrl"):
                current[field] = row[field]
        current["offeredTerms"].add(row["term"])
        for instructor in row["instructors"]:
            if not any(existing["name"] == instructor["name"] for existing in current["instructors"]):
                current["instructors"].append({"name": instructor["name"], "officialSourceUrl": instructor["sourceUrl"]})
    result = []
    for row in merged.values():
        row["id"] = course_id(row)
        row["instructors"].sort(key=lambda item: item["name"])
        offered_terms = sorted(row["offeredTerms"])
        row["firstTerm"] = offered_terms[0]
        row["lastTerm"] = offered_terms[-1]
        row["offeredTerms"] = offered_terms
        result.append({key: row[key] for key in ("id", "universityId", "term", "firstTerm", "lastTerm", "offeredTerms", "courseCode", "name", "department", "officialSourceUrl", "departmentSourceUrl", "instructors")})
    return sorted(result, key=lambda row: (row["universityId"], row["term"], row["department"], row["courseCode"]))


def sql_quote(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def committed_migration_names() -> set[str]:
    """List migrations committed in HEAD, ignoring index/worktree-only files."""
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "drizzle"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = normalize_space(result.stderr or result.stdout)[:300]
        raise RuntimeError(f"cannot verify committed migration immutability: {detail}")
    return {
        Path(line).name
        for line in result.stdout.splitlines()
        if normalize_space(line)
    }


def write_course_migrations(courses: list[dict], checked_at: str) -> list[str]:
    """Return the immutable base migration set; deployed migrations are never rewritten."""
    del courses, checked_at
    files = [f"{number:04d}_official_course_history_part_{number - 14:02d}.sql" for number in range(15, 21)]
    missing = [name for name in files if not (ROOT / "drizzle" / name).is_file()]
    if missing:
        raise FileNotFoundError(f"immutable base course migrations are missing: {missing}")
    return files


def write_niu_migrations(courses: list[dict], checked_at: str) -> list[str]:
    """Return the immutable NIU migration; deployed migrations are never rewritten."""
    del courses, checked_at
    name = "0052_niu_official_course_history_part_01.sql"
    if not (ROOT / "drizzle" / name).is_file():
        raise FileNotFoundError(f"immutable NIU migration is missing: {name}")
    return [name]


def write_completion_migrations(courses: list[dict], checked_at: str, target_schools: tuple[str, ...]) -> list[str]:
    """Generate one immutable, explicitly versioned coverage migration batch."""
    selected = [row for row in courses if row["universityId"] in target_schools]
    if not selected:
        raise ValueError("completion migration has no selected courses")
    timestamp = checked_at.replace("+00:00", ".000Z")
    school_list = ", ".join(sql_quote(school) for school in target_schools)
    blocks = [
        "-- Remove the explicitly excluded official category only within this batch's schools.\n"
        f"DELETE FROM course_ratings WHERE course_id IN (SELECT id FROM courses WHERE university_id IN ({school_list}) AND source_type = 'official' AND name LIKE '%專題研究%');\n"
        "--> statement-breakpoint\n"
        f"DELETE FROM course_instructors WHERE course_id IN (SELECT id FROM courses WHERE university_id IN ({school_list}) AND source_type = 'official' AND name LIKE '%專題研究%');\n"
        "--> statement-breakpoint\n"
        f"DELETE FROM courses WHERE university_id IN ({school_list}) AND source_type = 'official' AND name LIKE '%專題研究%';\n"
        "--> statement-breakpoint\n"
        "-- Replace only unrated official rows in the schools covered by this snapshot.\n"
        f"DELETE FROM course_instructors WHERE course_id IN (SELECT c.id FROM courses c WHERE c.university_id IN ({school_list}) AND c.source_type = 'official' AND NOT EXISTS (SELECT 1 FROM course_ratings cr WHERE cr.course_id = c.id));\n"
        "--> statement-breakpoint\n"
        f"DELETE FROM courses WHERE university_id IN ({school_list}) AND source_type = 'official' AND NOT EXISTS (SELECT 1 FROM course_ratings cr WHERE cr.course_id = courses.id);\n"
        "--> statement-breakpoint\n",
    ]
    for start in range(0, len(selected), 20):
        values = []
        for row in selected[start:start + 20]:
            semester = row["term"].rsplit("-", 1)[-1]
            values.append("(" + ", ".join(sql_quote(value) for value in (
                row["id"], row["universityId"], row["term"], row["firstTerm"], row["lastTerm"],
                ",".join(row["offeredTerms"]), row["courseCode"], row["name"], row["department"],
                row["officialSourceUrl"], row["departmentSourceUrl"], timestamp, timestamp,
                semester, "official",
            )) + ")")
        blocks.append("\n".join([
            "INSERT INTO courses (id, university_id, term, first_term, last_term, offered_terms, course_code, name, department, official_source_url, department_source_url, created_at, updated_at, semester, source_type) VALUES",
            ",\n".join(values),
            "ON CONFLICT(id) DO UPDATE SET term=excluded.term, first_term=excluded.first_term, last_term=excluded.last_term, offered_terms=excluded.offered_terms, course_code=excluded.course_code, name=excluded.name, department=excluded.department, official_source_url=excluded.official_source_url, department_source_url=excluded.department_source_url, semester=excluded.semester, source_type='official', updated_at=excluded.updated_at;",
            "--> statement-breakpoint\n",
        ]))

    instructors = [(row, instructor) for row in selected for instructor in row["instructors"]]
    for start in range(0, len(instructors), 40):
        values = []
        for row, instructor in instructors[start:start + 40]:
            professor_id = (
                f"(SELECT id FROM professors WHERE university_id={sql_quote(row['universityId'])} "
                f"AND name={sql_quote(instructor['name'])} LIMIT 1)"
            )
            values.append("(" + ", ".join((
                sql_quote(row["id"]), sql_quote(instructor["name"]), professor_id,
                sql_quote(instructor.get("officialSourceUrl", "")), sql_quote(timestamp),
            )) + ")")
        blocks.append("\n".join([
            "INSERT INTO course_instructors (course_id, instructor_name, professor_id, official_source_url, created_at) VALUES",
            ",\n".join(values),
            "ON CONFLICT(course_id, instructor_name) DO UPDATE SET professor_id=excluded.professor_id, official_source_url=excluded.official_source_url;",
            "--> statement-breakpoint\n",
        ]))
    blocks.append(
        "INSERT INTO app_runtime_state (key, value, updated_at)\n"
        f"VALUES ('course_coverage_version', {sql_quote(checked_at)}, CURRENT_TIMESTAMP)\n"
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;\n"
        "--> statement-breakpoint\nPRAGMA optimize;\n"
    )

    migration_dir = ROOT / "drizzle"
    if COMPLETION_MIGRATION_BATCH < 1:
        raise ValueError("COMPLETION_MIGRATION_BATCH must be positive")
    batch_stem = (
        "complete_official_course_coverage"
        if COMPLETION_MIGRATION_BATCH == 1
        else f"complete_official_course_coverage_batch_{COMPLETION_MIGRATION_BATCH:02d}"
    )
    batch_name_pattern = re.compile(
        rf"^\d{{4}}_{re.escape(batch_stem)}_part_\d+\.sql$"
    )
    committed_batch = sorted(
        name for name in committed_migration_names()
        if batch_name_pattern.fullmatch(name)
    )
    if committed_batch:
        raise RuntimeError(
            f"completion batch {COMPLETION_MIGRATION_BATCH} already has committed migrations "
            f"({', '.join(committed_batch)}); bump COMPLETION_MIGRATION_BATCH"
        )

    pattern = f"[0-9][0-9][0-9][0-9]_{batch_stem}_part_*.sql"
    current_batch = sorted(migration_dir.glob(pattern))
    current_names = {path.name for path in current_batch}
    current_numbers = [int(path.name[:4]) for path in current_batch]
    other_numbers = [
        int(match.group(1))
        for path in migration_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if path.name not in current_names and (match := re.match(r"(\d{4})_", path.name))
    ]
    start_number = min(current_numbers) if current_numbers else max(other_numbers, default=0) + 1
    header = "-- Append-only official course coverage generated from university-owned public sources.\n"
    max_bytes = 850 * 1024
    chunks: list[str] = []
    current = header
    for block in blocks:
        if len(current.encode("utf-8")) + len(block.encode("utf-8")) > max_bytes and current != header:
            chunks.append(current)
            current = header
        current += block
    if current != header:
        chunks.append(current)

    files = [
        f"{start_number + index:04d}_{batch_stem}_part_{index + 1:02d}.sql"
        for index in range(len(chunks))
    ]
    occupied_numbers = set(other_numbers)
    collisions = [
        name for index, name in enumerate(files)
        if start_number + index in occupied_numbers
    ]
    if collisions:
        raise RuntimeError(
            f"completion batch would collide with existing migrations ({', '.join(collisions)}); "
            "bump COMPLETION_MIGRATION_BATCH"
        )

    for path in current_batch:
        path.unlink()
    for name, content in zip(files, chunks, strict=True):
        (migration_dir / name).write_text(content, encoding="utf-8")
    return files


def overlay_nsysu_supplement(report_payload: dict) -> None:
    """Overlay the separately validated NSYSU completion report when present.

    The base importer does not automate NSYSU's CAPTCHA form.  A dedicated
    importer uses the separate public OPEN_CRS course-handbook reports.  This
    fail-closed composer prevents a later base refresh from resurrecting the
    older restricted/zero row after that supplemental batch has been verified.
    """
    detail_path = DB / "nsysu-course-report.generated.json"
    if not detail_path.is_file():
        return
    try:
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    expected_terms = [f"{year}-{semester}" for year, semester in TERM_PAIRS]
    migrations = detail.get("migrationFiles") or []
    valid = (
        detail.get("status") == "imported"
        and detail.get("policy", {}).get("officialUniversityDomainsOnly") is True
        and detail.get("policy", {}).get("captchaBypassed") is False
        and detail.get("policy", {}).get("failClosedResponseValidation") is True
        and detail.get("availableTerms") == expected_terms
        and detail.get("missingTerms") == []
        and detail.get("failedDepartmentQueries") == []
        and int(detail.get("unitCatalogCount") or 0) >= 300
        and int(detail.get("successfulDepartmentQueries") or 0)
        == int(detail.get("unitCatalogCount") or 0) * len(expected_terms)
        and int(detail.get("verifiedCourses") or 0) > 0
        and int(detail.get("publishedCourseInstructorCards") or 0)
        >= int(detail.get("verifiedCourses") or 0)
        and migrations
        and all((ROOT / "drizzle" / name).is_file() for name in migrations)
    )
    if not valid:
        return

    replacement = {
        "status": "imported",
        "officialIndex": detail["officialIndex"],
        "note": (
            "透過校方公開 OPEN_CRS 課程手冊查詢補入；"
            "未自動化或繞過學生歷史查詢的人工驗證碼"
        ),
        "universityId": "nsysu",
        "checkedAt": detail["checkedAt"],
        "parsedOfferings": detail["parsedOfferings"],
        "verifiedOfferings": detail["verifiedCourses"],
        "verifiedCourses": detail["verifiedCourses"],
        "publishedCourseInstructorCards": detail["publishedCourseInstructorCards"],
        "rejectedWithoutCurrentFaculty": detail["rejectedWithoutCurrentInstructor"],
        "availableTerms": detail["availableTerms"],
        "missingTerms": detail["missingTerms"],
        "activeFacultyCount": detail["activeFacultyPageCount"],
        "activeInstructorCount": detail["activeInstructorCount"],
        "activeCourseReportEvidenceCount": detail["activeCourseReportEvidenceCount"],
        "detailReport": "db/nsysu-course-report.generated.json",
        "supplementalMigrationFiles": migrations,
    }
    report_payload["schools"] = [
        replacement if school.get("universityId") == "nsysu" else school
        for school in report_payload["schools"]
    ]
    base_count = int(report_payload["courseCount"])
    report_payload["baseImporterCourseCount"] = base_count
    report_payload["nsysuSupplementalCourseCount"] = detail["verifiedCourses"]
    report_payload["nsysuSupplementalInstructorCount"] = detail["publishedCourseInstructorCards"]
    report_payload["courseCount"] = base_count + detail["verifiedCourses"]
    report_payload["publishedCourseCount"] = report_payload["courseCount"]
    report_payload["nsysuMigrationFiles"] = migrations
    report_payload["supplementalCheckedAt"] = detail["checkedAt"]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    active = load_active_faculty()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reports = {
        school: {
            **status,
            "universityId": school,
            "checkedAt": checked_at,
            "parsedOfferings": 0,
            "verifiedOfferings": 0,
            "rejectedWithoutCurrentFaculty": 0,
            "availableTerms": [],
            "missingTerms": (
                [f"{year}-{semester}" for year, semester in TERM_PAIRS]
                if status["status"] == "restricted"
                else []
            ),
        }
        for school, status in COURSE_SOURCE_STATUS.items()
    }
    rows = []
    rows.extend(parse_ntu(active["ntu"], reports["ntu"]))
    rows.extend(parse_nthu(active["nthu"], reports["nthu"]))
    rows.extend(parse_nycu(active["nycu"], reports["nycu"]))
    rows.extend(parse_ncu(active["ncu"], reports["ncu"]))
    rows.extend(parse_nchu(active["nchu"], reports["nchu"]))
    rows.extend(parse_ccu(active["ccu"], reports["ccu"]))
    rows.extend(parse_ntust(active["ntust"], reports["ntust"]))
    rows.extend(parse_ntut(active["ntut"], reports["ntut"]))
    rows.extend(parse_niu(active["niu"], reports["niu"]))
    covered_schools = {row["universityId"] for row in rows}
    rows.extend(
        row for row in current_verified_fallbacks()
        if row["universityId"] not in covered_schools
    )
    courses = deduplicate(rows)
    by_school = defaultdict(list)
    for course in courses:
        by_school[course["universityId"]].append(course)
    for school, report in reports.items():
        report["verifiedOfferings"] = len(by_school[school])
        report["activeFacultyCount"] = len(active.get(school, {}))
    reports["nthu"]["availableTerms"] = sorted({row["term"] for row in by_school["nthu"]})
    payload = json.dumps(courses, ensure_ascii=False, indent=2)
    (DB / "course-seeds.generated.ts").write_text(
        "import type { CourseSeed } from './course-seeds';\n\n"
        "// Generated by scripts/import-official-course-history.py. Do not edit by hand.\n"
        f"export const courseSeeds: CourseSeed[] = {payload};\n",
        encoding="utf-8",
    )
    report_payload = {
        "policy": {
            "earliestAcademicYear": EARLIEST_YEAR,
            "latestAcademicYear": CURRENT_YEAR,
            "officialUniversityDomainsOnly": True,
            "requiresCurrentOfficialFacultyEvidence": True,
            "inactiveOrUnverifiedInstructorsPublished": False,
        },
        "checkedAt": checked_at,
        "courseCount": len(courses),
        "baseSnapshotCourseCount": 37_625,
        "completionCourseCount": sum(
            len(by_school[school]) for school in ("nthu", "nycu", "nchu", "ntust")
        ),
        "schools": list(reports.values()),
    }
    report_payload["courseMigrationFiles"] = write_course_migrations(courses, checked_at)
    report_payload["niuMigrationFiles"] = write_niu_migrations(courses, checked_at)
    report_payload["completionMigrationFiles"] = write_completion_migrations(
        courses,
        checked_at,
        ("nthu", "nycu", "nchu", "ntust"),
    )
    overlay_nsysu_supplement(report_payload)
    (DB / "course-import-report.generated.json").write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"courses": len(courses), "bySchool": {school: len(values) for school, values in by_school.items()}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
