#!/usr/bin/env python3
"""Import NSYSU courses from the university's public course reports.

The student-facing history search uses a human CAPTCHA.  This importer does
not automate or bypass it.  Instead it reads the separate, university-owned
OPEN_CRS course handbook report, which is public, indexed, and supports the
same academic years without authentication.

Only instructors who are evidenced by either a current official faculty page
or the official 115-1 course report are published.  The generated D1
migrations are append-only and preserve any rows that already have ratings.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db"
DRIZZLE = ROOT / "drizzle"
CACHE = ROOT / ".course-cache" / "nsysu"
REPORT = DB / "nsysu-course-report.generated.json"
AGGREGATE_REPORT = DB / "course-import-report.generated.json"

UNIVERSITY_ID = "nsysu"
OFFICIAL_HOST_SUFFIX = "nsysu.edu.tw"
EARLIEST_YEAR = 106
CURRENT_YEAR = 115
CURRENT_TERM = f"{CURRENT_YEAR}-1"
TERMS = tuple(
    (year, semester)
    for year in range(EARLIEST_YEAR, CURRENT_YEAR)
    for semester in (1, 2)
) + ((CURRENT_YEAR, 1),)
MIGRATION_BATCH = 1
MAX_MIGRATION_BYTES = 850 * 1024
MIN_UNIT_CATALOG_SIZE = 300
MIN_OFFERINGS_PER_TERM = 1_000
EXPECTED_REPORT_HEADERS = (
    "限修", "多門", "級班", "課號", "課程名稱", "教授姓名", "必選修", "學分數",
    "學年/期", "正課", "實習", "時間教室", "人數", "外校生人數", "備註",
)
UNIT_CATALOG_ANCHORS = {"AB0A", "B101", "B302", "M301", "N451", "P301", "PA03"}
USER_AGENT = "WZUNAA-official-course-audit/4.0 (+https://map.scmwcscr.com)"

COURSE_REPORT_ENDPOINT = "https://selcrs.nsysu.edu.tw/OPEN_CRS/crs_open.asp"
OFFICIAL_COURSE_INDEX = "https://selcrs.nsysu.edu.tw/smain.asp?eng=0"
OFFICIAL_UNIT_DIRECTORY = "https://www.nsysu.edu.tw/p/412-1000-88.php?Lang=zh-tw"


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def strip_html(value: str) -> str:
    return normalize_space(re.sub(r"<[^>]+>", " ", value))


def normalize_name(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.sub(r"(?:教授|副教授|助理教授|講師|老師)$", "", text)
    return re.sub(r"[^\u3400-\u9fff]", "", text)


def split_instructors(value: object) -> list[str]:
    result: list[str] = []
    for item in re.split(r"[、,，;/／；\n]+", str(value or "")):
        name = normalize_name(item)
        if not 2 <= len(name) <= 8:
            continue
        if name in {"指導教授", "合授教師", "未定", "待聘", "無"}:
            continue
        if name not in result:
            result.append(name)
    return result


def official_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (
        host == OFFICIAL_HOST_SUFFIX or host.endswith("." + OFFICIAL_HOST_SUFFIX)
    ):
        raise ValueError(f"non-official NSYSU URL rejected: {value}")
    return value


def cache_path(kind: str, identity: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]", "-", identity)
    return CACHE / kind / f"{safe}.html"


def fetch_cached(
    url: str,
    path: Path,
    *,
    refresh: bool,
    minimum_size: int = 50,
    validator: Callable[[bytes], None] | None = None,
) -> bytes:
    official_url(url)
    if not refresh and path.is_file() and path.stat().st_size >= minimum_size:
        cached = path.read_bytes()
        try:
            if validator:
                validator(cached)
            return cached
        except ValueError:
            # Old interrupted/error responses are never trusted merely because
            # they were cached.  Fetch a fresh official response below.
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        })
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                official_url(response.geturl())
                payload = response.read()
            if len(payload) < minimum_size:
                raise ValueError(f"official response is unexpectedly small ({len(payload)} bytes): {url}")
            if validator:
                validator(payload)
            path.write_bytes(payload)
            time.sleep(0.05)
            return payload
        except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        tag = tag.lower()
        if tag == "tr":
            if self.current_row:
                if self.current_cell is not None:
                    self.current_row.append(normalize_space("".join(self.current_cell)))
                self.rows.append(self.current_row)
            self.current_row = []
            self.current_cell = None
        elif tag in {"td", "th"} and self.current_row is not None:
            if self.current_cell is not None:
                self.current_row.append(normalize_space("".join(self.current_cell)))
            self.current_cell = []
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.append("／")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_row.append(normalize_space("".join(self.current_cell)))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = None


def report_url(year: int, semester: int, department_code: str) -> str:
    query = urllib.parse.urlencode({
        "ACTION": "2",
        "QM_ACTION": "2",
        "PRTCRS": "2",
        "QM_DATA_ARRAY": "2",
        "QM_DPT_COD": department_code,
        "QM_SECT_COD": "0",
        "QM_SEM": str(semester),
        "QM_SYEAR": str(year),
        "ROWNUM": "1",
    })
    return official_url(f"{COURSE_REPORT_ENDPOINT}?{query}")


def course_record_url(year: int, semester: int, department_code: str, course_code: str) -> str:
    query = urllib.parse.urlencode({
        "ACTION": "2",
        "QM_ACTION": "2",
        "QM_DATA_ARRAY": "1",
        "QM_DPT_COD": department_code,
        "QM_SECT_COD": "0",
        "QM_SEM": str(semester),
        "QM_SYEAR": str(year),
        "QM_CRSNO": course_code,
        "ROWNUM": "1",
    })
    return official_url(f"{COURSE_REPORT_ENDPOINT}?{query}")


def parse_department_options(page: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(
        r"<option\s+value\s*=\s*['\"]?([A-Z0-9]{4})(?=[\s>'\"])[^>]*>(.*?)</option>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        code = match.group(1).upper()
        label = strip_html(match.group(2))
        if label.startswith(code):
            label = label[len(code):].strip()
        result[code] = label or code
    return result


def parse_department_catalog(payload: bytes) -> dict[str, str]:
    page = payload.decode("utf-8")
    selector_pattern = (
        r"<select\b[^>]*\bname\s*=\s*['\"]?QM_DPT_COD\b[^>]*>.*?</select>"
    )
    selectors = re.findall(selector_pattern, page, flags=re.IGNORECASE | re.DOTALL)
    if len(selectors) != 1:
        raise ValueError(f"official NSYSU unit catalog has {len(selectors)} unit selectors")
    codes = parse_department_options(selectors[0])
    if len(codes) < MIN_UNIT_CATALOG_SIZE:
        raise ValueError(f"official NSYSU unit catalog is unexpectedly small: {len(codes)}")
    missing_anchors = UNIT_CATALOG_ANCHORS.difference(codes)
    if missing_anchors:
        raise ValueError(
            "official NSYSU unit catalog is missing stable units: "
            + ", ".join(sorted(missing_anchors))
        )
    year_selectors = re.findall(
        r"<select\b[^>]*\bname\s*=\s*['\"]?QM_SYEAR\b[^>]*>.*?</select>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(year_selectors) != 1:
        raise ValueError("official NSYSU unit catalog year selector is missing or ambiguous")
    for year in (EARLIEST_YEAR, CURRENT_YEAR):
        if not re.search(
            rf"<option\b[^>]*\bvalue\s*=\s*['\"]?0*{year}(?=[\s>'\"])",
            year_selectors[0],
            flags=re.IGNORECASE,
        ):
            raise ValueError(f"official NSYSU unit catalog does not expose academic year {year}")
    return codes


def validate_department_catalog(payload: bytes) -> None:
    parse_department_catalog(payload)


def javascript_field_value(page: str, field: str) -> str | None:
    matches = re.findall(
        rf"document\.all\.{re.escape(field)}\.value\s*=\s*(['\"])(.*?)\1\s*;",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if len(matches) != 1:
        return None
    return normalize_space(matches[0][1])


def validate_course_report_payload(
    payload: bytes,
    *,
    year: int,
    semester: int,
    department_code: str,
) -> str:
    """Validate one read-only OPEN_CRS report and return data/empty.

    OPEN_CRS sometimes answers with tiny fragments or a generic form while
    still returning HTTP 200.  A response is accepted only when its own script
    echoes the requested query and it contains either the official course table
    or the explicit no-data result.  This prevents a partial server response
    from being mistaken for a successfully queried empty unit.
    """
    if len(payload) < 600:
        raise ValueError(f"official course report is unexpectedly small: {len(payload)} bytes")
    page = payload.decode("utf-8")
    expected = {
        "QM_SYEAR": str(year),
        "QM_SEM": str(semester),
        "PRTCRS": "2",
        "QM_DPT_COD": department_code.upper(),
        "QM_SECT_COD": "0",
        "QM_DATA_ARRAY": "2",
    }
    for field, value in expected.items():
        actual = javascript_field_value(page, field)
        if actual is None:
            raise ValueError(f"official course report did not echo {field}")
        if (actual.upper() if field == "QM_DPT_COD" else actual) != value:
            raise ValueError(f"official course report echoed the wrong {field}: {actual!r}")
    action_checks = re.findall(
        r"document\.all\.QM_ACTION\[1\]\.checked\s*=\s*true\s*;",
        page,
        flags=re.IGNORECASE,
    )
    if len(action_checks) != 1:
        raise ValueError("official course report action mode is missing or ambiguous")

    if re.search(r"查\s*無\s*資\s*料", page):
        if len(payload) > 1_500:
            raise ValueError("official empty course report has an unexpected payload shape")
        if not re.search(r"<title>\s*開課資料維護\s*</title>", page, re.IGNORECASE):
            raise ValueError("official empty course report title is missing")
        if re.search(r"<table\b|<form\b|開課系所\s*:", page, re.IGNORECASE):
            raise ValueError("official empty course report contains an unexpected form or table")
        if not re.search(
            r"</script>\s*查\s*無\s*資\s*料\s*</center></div>\s*\Z",
            page,
            flags=re.IGNORECASE,
        ):
            raise ValueError("official empty course report suffix is invalid")
        return "empty"

    if len(payload) < 5_000:
        raise ValueError("official data course report is unexpectedly small")
    if not re.search(r"</table></body></html></center></div>\s*\Z", page, re.IGNORECASE):
        raise ValueError("official data course report suffix is incomplete")
    headings = [
        (normalize_space(match.group(1)), match.group(2))
        for match in re.finditer(
            r"開課系所\s*:\s*([^<&]+).*?\((\d{3}[0-3])\)\s*</b>",
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    if not headings or any(not department for department, _ in headings):
        raise ValueError("official course report is missing its department heading")
    if {term for _, term in headings} != {f"{year}{semester}"}:
        raise ValueError("official course report contains the wrong or mixed term headings")
    if len({department for department, _ in headings}) != 1:
        raise ValueError("official course report contains mixed department headings")

    parser = TableParser()
    parser.feed(page)
    normalized_rows = [tuple(re.sub(r"\s+", "", cell) for cell in row) for row in parser.rows]
    if EXPECTED_REPORT_HEADERS not in normalized_rows:
        raise ValueError("official course report is missing its course table header")
    course_rows = []
    for raw_row, normalized_row in zip(parser.rows, normalized_rows, strict=True):
        if len(raw_row) < len(EXPECTED_REPORT_HEADERS):
            continue
        if len(raw_row) != len(EXPECTED_REPORT_HEADERS):
            raise ValueError("official course report contains a malformed wide row")
        if normalized_row == EXPECTED_REPORT_HEADERS:
            continue
        course_code = normalize_space(raw_row[3]).upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,24}", course_code):
            raise ValueError("official course report contains a malformed course row")
        if not normalize_space(raw_row[4]) or not normalize_space(raw_row[5]):
            raise ValueError("official course report contains an incomplete course row")
        course_rows.append(raw_row)
    if not course_rows:
        raise ValueError("official data course report contains no complete course row")
    return "data"


def load_static_department_codes(*, refresh: bool) -> dict[str, str]:
    """Read the complete 82–115 unit catalog embedded in OPEN_CRS.

    The student query's dependent dropdown only returns detailed units for the
    most recent completed term.  OPEN_CRS itself embeds the full historical
    catalog, so it is the authoritative fallback for older terms.
    """
    url = course_record_url(CURRENT_YEAR, 1, "B302", "")
    payload = fetch_cached(
        url,
        cache_path("catalog", "all-departments-v2"),
        refresh=refresh,
        minimum_size=500,
        validator=validate_department_catalog,
    )
    result = parse_department_catalog(payload)
    if len(result) < MIN_UNIT_CATALOG_SIZE:
        raise RuntimeError(f"official NSYSU unit catalog is unexpectedly small: {len(result)}")
    return result


def parse_course_report(
    payload: bytes,
    *,
    year: int,
    semester: int,
    department_code: str,
    fallback_department: str,
) -> list[dict]:
    state = validate_course_report_payload(
        payload,
        year=year,
        semester=semester,
        department_code=department_code,
    )
    if state == "empty":
        return []
    page = payload.decode("utf-8", "replace")
    department_match = re.search(r"開課系所\s*:\s*([^<&]+)", page)
    department = normalize_space(department_match.group(1)) if department_match else fallback_department
    parser = TableParser()
    parser.feed(page)
    rows: list[dict] = []
    for cells in parser.rows:
        if len(cells) < 15:
            continue
        course_code = normalize_space(cells[3]).upper()
        name = normalize_space(cells[4])
        instructors = split_instructors(cells[5])
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,24}", course_code):
            continue
        if not name or name == "課程名稱" or not instructors:
            continue
        rows.append({
            "universityId": UNIVERSITY_ID,
            "term": f"{year}-{semester}",
            "courseCode": course_code,
            "name": name,
            "department": department,
            "departmentCode": department_code,
            "officialSourceUrl": course_record_url(year, semester, department_code, course_code),
            "teachers": instructors,
        })
    return rows


def load_term(
    year: int,
    semester: int,
    *,
    workers: int,
    refresh: bool,
    static_codes: dict[str, str],
) -> tuple[list[dict], dict]:
    # OPEN_CRS embeds one complete historical unit catalog.  The dependent
    # student dropdown is intentionally not used because older terms expose
    # only a small subset there even though the concrete unit reports exist.
    department_codes = dict(static_codes)
    failures: list[dict[str, str]] = []
    successful_queries = 0
    empty_queries = 0

    def fetch_department(item: tuple[str, str]) -> tuple[list[dict], str]:
        code, label = item
        url = report_url(year, semester, code)
        validator = lambda body: validate_course_report_payload(
            body,
            year=year,
            semester=semester,
            department_code=code,
        )
        payload = fetch_cached(
            url,
            cache_path("courses", f"{year}{semester}-{code}"),
            refresh=refresh,
            minimum_size=500,
            validator=validator,
        )
        state = validate_course_report_payload(
            payload, year=year, semester=semester, department_code=code
        )
        return (
            parse_course_report(
                payload,
                year=year,
                semester=semester,
                department_code=code,
                fallback_department=label,
            ),
            state,
        )

    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_department, item): item for item in department_codes.items()}
        for future in concurrent.futures.as_completed(futures):
            code, _ = futures[future]
            try:
                department_rows, state = future.result()
                rows.extend(department_rows)
                successful_queries += 1
                if state == "empty":
                    empty_queries += 1
            except Exception as error:  # keep a complete, reviewable failure report
                failures.append({
                    "departmentCode": code,
                    "error": type(error).__name__,
                    "message": normalize_space(error)[:180],
                })
    rows.sort(key=lambda row: (row["departmentCode"], row["courseCode"], row["name"]))
    return rows, {
        "term": f"{year}-{semester}",
        "departmentQueries": len(department_codes),
        "successfulDepartmentQueries": successful_queries,
        "emptyDepartmentQueries": empty_queries,
        "parsedOfferings": len(rows),
        "failedDepartmentQueries": sorted(failures, key=lambda row: row["departmentCode"]),
    }


def load_current_official_faculty() -> dict[str, dict]:
    source_path = DB / "professor-candidates.generated.json"
    rows = json.loads(source_path.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    for row in rows:
        if row.get("universityId") != UNIVERSITY_ID:
            continue
        name = normalize_name(row.get("name"))
        source = str(row.get("sourceUrl") or "")
        if not 2 <= len(name) <= 8:
            continue
        try:
            source = official_url(source)
        except ValueError:
            continue
        result[name] = {
            "name": name,
            "department": normalize_space(row.get("department")),
            "sourceUrl": source,
            "evidence": "current-faculty-page",
        }
    return result


def normalize_department_identity(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.sub(r"(?:碩士|博士|學士)?(?:在職)?(?:專班|班)$", "", text)
    text = re.sub(r"(?:學系|研究所|學位學程|學程|中心|學院|系|所|班)", "", text)
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", text).lower()


def load_department_sites() -> list[dict]:
    rows = json.loads((DB / "department-sites.generated.json").read_text(encoding="utf-8"))
    return [row for row in rows if row.get("universityId") == UNIVERSITY_ID]


def department_url(department: str, sites: list[dict]) -> str:
    target = normalize_department_identity(department)
    ranked: list[tuple[int, int, str]] = []
    for row in sites:
        name = normalize_department_identity(row.get("name"))
        score = (
            1000 if row.get("name") == department
            else 900 if name and name == target
            else 700 if min(len(name), len(target)) >= 2 and (name in target or target in name)
            else 0
        )
        source = row.get("websiteUrl") or row.get("officialDirectoryUrl")
        if score and source:
            try:
                ranked.append((score, len(name), official_url(source)))
            except ValueError:
                continue
    return max(ranked)[2] if ranked else official_url(OFFICIAL_UNIT_DIRECTORY)


def course_id(course_code: str) -> str:
    identity = f"{UNIVERSITY_ID}\0{course_code}"
    return f"course-{UNIVERSITY_ID}-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def deduplicate(rows: list[dict], active: dict[str, dict], sites: list[dict]) -> tuple[list[dict], dict]:
    merged: dict[str, dict] = {}
    counters = {
        "excludedSpecialResearch": 0,
        "rejectedWithoutCurrentInstructor": 0,
        "verifiedHistoricalOfferings": 0,
    }
    for row in rows:
        if "專題研究" in row["name"]:
            counters["excludedSpecialResearch"] += 1
            continue
        instructors = [active[name] for name in row["teachers"] if name in active]
        if not instructors:
            counters["rejectedWithoutCurrentInstructor"] += 1
            continue
        counters["verifiedHistoricalOfferings"] += 1
        key = row["courseCode"]
        current = merged.get(key)
        if current is None:
            current = {
                **row,
                "id": course_id(row["courseCode"]),
                "offeredTerms": set(),
                "instructors": {},
            }
            merged[key] = current
        elif row["term"] > current["term"]:
            for field in ("term", "name", "department", "departmentCode", "officialSourceUrl"):
                current[field] = row[field]
        current["offeredTerms"].add(row["term"])
        for instructor in instructors:
            current["instructors"][instructor["name"]] = {
                "name": instructor["name"],
                "officialSourceUrl": official_url(instructor["sourceUrl"]),
                "evidence": instructor["evidence"],
            }

    result: list[dict] = []
    for row in merged.values():
        terms = sorted(row["offeredTerms"])
        instructors = sorted(row["instructors"].values(), key=lambda item: item["name"])
        result.append({
            "id": row["id"],
            "universityId": UNIVERSITY_ID,
            "term": row["term"],
            "firstTerm": terms[0],
            "lastTerm": terms[-1],
            "offeredTerms": terms,
            "semester": row["term"].rsplit("-", 1)[-1],
            "courseCode": row["courseCode"],
            "name": row["name"],
            "department": row["department"],
            "officialSourceUrl": official_url(row["officialSourceUrl"]),
            "departmentSourceUrl": department_url(row["department"], sites),
            "instructors": instructors,
        })
    result.sort(key=lambda row: (row["department"], row["name"], row["courseCode"]))
    return result, counters


def sql_quote(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def committed_migration_names() -> set[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "drizzle"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown git error").strip()
        raise RuntimeError(f"cannot verify committed migration immutability: {detail}")
    return {Path(line).name for line in result.stdout.splitlines() if line.strip()}


def migration_blocks(courses: list[dict], checked_at: str) -> list[str]:
    timestamp = checked_at.replace("+00:00", ".000Z")
    blocks = [
        "-- Remove the explicitly excluded official category for NSYSU only.\n"
        "DELETE FROM course_ratings WHERE course_id IN (SELECT id FROM courses WHERE university_id = 'nsysu' AND source_type = 'official' AND name LIKE '%專題研究%');\n"
        "--> statement-breakpoint\n"
        "DELETE FROM course_instructors WHERE course_id IN (SELECT id FROM courses WHERE university_id = 'nsysu' AND source_type = 'official' AND name LIKE '%專題研究%');\n"
        "--> statement-breakpoint\n"
        "DELETE FROM courses WHERE university_id = 'nsysu' AND source_type = 'official' AND name LIKE '%專題研究%';\n"
        "--> statement-breakpoint\n"
        "-- Rebuild every official instructor link from current official evidence.\n"
        "-- Ratings remain stored even if an inactive instructor card is removed.\n"
        "DELETE FROM course_instructors WHERE course_id IN (SELECT c.id FROM courses c WHERE c.university_id = 'nsysu' AND c.source_type = 'official');\n"
        "--> statement-breakpoint\n"
        "-- Replace only unrated official course parents so submitted ratings are never discarded.\n"
        "DELETE FROM courses WHERE university_id = 'nsysu' AND source_type = 'official' AND NOT EXISTS (SELECT 1 FROM course_ratings cr WHERE cr.course_id = courses.id);\n"
        "--> statement-breakpoint\n"
    ]
    for start in range(0, len(courses), 20):
        values = []
        for row in courses[start:start + 20]:
            values.append("(" + ", ".join(sql_quote(value) for value in (
                row["id"], UNIVERSITY_ID, row["term"], row["firstTerm"], row["lastTerm"],
                ",".join(row["offeredTerms"]), row["courseCode"], row["name"], row["department"],
                row["officialSourceUrl"], row["departmentSourceUrl"], timestamp, timestamp,
                row["semester"], "official",
            )) + ")")
        blocks.append("\n".join((
            "INSERT INTO courses (id, university_id, term, first_term, last_term, offered_terms, course_code, name, department, official_source_url, department_source_url, created_at, updated_at, semester, source_type) VALUES",
            ",\n".join(values),
            "ON CONFLICT(id) DO UPDATE SET term=excluded.term, first_term=excluded.first_term, last_term=excluded.last_term, offered_terms=excluded.offered_terms, course_code=excluded.course_code, name=excluded.name, department=excluded.department, official_source_url=excluded.official_source_url, department_source_url=excluded.department_source_url, semester=excluded.semester, source_type='official', updated_at=excluded.updated_at;",
            "--> statement-breakpoint\n",
        )))

    instructor_rows = [(course, instructor) for course in courses for instructor in course["instructors"]]
    for start in range(0, len(instructor_rows), 40):
        values = []
        for course, instructor in instructor_rows[start:start + 40]:
            professor_id = (
                f"(SELECT id FROM professors WHERE university_id='nsysu' "
                f"AND name={sql_quote(instructor['name'])} LIMIT 1)"
            )
            values.append("(" + ", ".join((
                sql_quote(course["id"]), sql_quote(instructor["name"]), professor_id,
                sql_quote(instructor["officialSourceUrl"]), sql_quote(timestamp),
            )) + ")")
        blocks.append("\n".join((
            "INSERT INTO course_instructors (course_id, instructor_name, professor_id, official_source_url, created_at) VALUES",
            ",\n".join(values),
            "ON CONFLICT(course_id, instructor_name) DO UPDATE SET professor_id=excluded.professor_id, official_source_url=excluded.official_source_url;",
            "--> statement-breakpoint\n",
        )))
    blocks.append(
        "INSERT INTO app_runtime_state (key, value, updated_at)\n"
        f"VALUES ('nsysu_course_coverage_version', {sql_quote(checked_at)}, CURRENT_TIMESTAMP)\n"
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;\n"
        "--> statement-breakpoint\nPRAGMA optimize;\n"
    )
    return blocks


def write_migrations(courses: list[dict], checked_at: str) -> list[str]:
    if not courses:
        raise ValueError("NSYSU migration cannot be generated from an empty snapshot")
    batch_stem = f"nsysu_official_course_history_batch_{MIGRATION_BATCH:02d}"
    pattern = re.compile(rf"^\d{{4}}_{re.escape(batch_stem)}_part_\d+\.sql$")
    committed_batch = sorted(name for name in committed_migration_names() if pattern.fullmatch(name))
    if committed_batch:
        raise RuntimeError(
            f"{batch_stem} already has committed migrations ({', '.join(committed_batch)}); "
            "increment MIGRATION_BATCH before creating a refresh"
        )

    current_batch = sorted(DRIZZLE.glob(f"[0-9][0-9][0-9][0-9]_{batch_stem}_part_*.sql"))
    current_names = {path.name for path in current_batch}
    current_numbers = [int(path.name[:4]) for path in current_batch]
    other_numbers = [
        int(match.group(1))
        for path in DRIZZLE.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if path.name not in current_names and (match := re.match(r"(\d{4})_", path.name))
    ]
    start_number = min(current_numbers) if current_numbers else max(other_numbers, default=0) + 1

    header = (
        "-- Append-only NSYSU course coverage from the university-owned OPEN_CRS report.\n"
        "-- The CAPTCHA-protected student history form is not automated or bypassed.\n"
    )
    chunks: list[str] = []
    current = header
    for block in migration_blocks(courses, checked_at):
        if len(current.encode("utf-8")) + len(block.encode("utf-8")) > MAX_MIGRATION_BYTES and current != header:
            chunks.append(current)
            current = header
        current += block
    if current != header:
        chunks.append(current)

    files = [
        f"{start_number + index:04d}_{batch_stem}_part_{index + 1:02d}.sql"
        for index in range(len(chunks))
    ]
    occupied = set(other_numbers)
    collisions = [name for index, name in enumerate(files) if start_number + index in occupied]
    if collisions:
        raise RuntimeError(f"migration number collision: {', '.join(collisions)}")

    for path in current_batch:
        path.unlink()
    for name, content in zip(files, chunks, strict=True):
        (DRIZZLE / name).write_text(content, encoding="utf-8", newline="\n")
    return files


def update_aggregate_course_report(report: dict) -> None:
    """Make the older multi-school audit aware of this supplemental batch."""
    if not AGGREGATE_REPORT.is_file():
        return
    aggregate = json.loads(AGGREGATE_REPORT.read_text(encoding="utf-8"))
    schools = list(aggregate.get("schools") or [])
    replacement = {
        "status": "imported",
        "officialIndex": report["officialIndex"],
        "note": (
            "透過校方公開 OPEN_CRS 課程手冊查詢補入；"
            "未自動化或繞過學生歷史查詢的人工驗證碼"
        ),
        "universityId": UNIVERSITY_ID,
        "checkedAt": report["checkedAt"],
        "parsedOfferings": report["parsedOfferings"],
        "verifiedOfferings": report["verifiedCourses"],
        "verifiedCourses": report["verifiedCourses"],
        "publishedCourseInstructorCards": report["publishedCourseInstructorCards"],
        "rejectedWithoutCurrentFaculty": report["rejectedWithoutCurrentInstructor"],
        "availableTerms": report["availableTerms"],
        "missingTerms": report["missingTerms"],
        "activeFacultyCount": report["activeFacultyPageCount"],
        "activeInstructorCount": report["activeInstructorCount"],
        "activeCourseReportEvidenceCount": report["activeCourseReportEvidenceCount"],
        "detailReport": "db/nsysu-course-report.generated.json",
        "supplementalMigrationFiles": report["migrationFiles"],
    }
    replaced = False
    for index, school in enumerate(schools):
        if school.get("universityId") == UNIVERSITY_ID:
            schools[index] = replacement
            replaced = True
            break
    if not replaced:
        schools.append(replacement)
    aggregate["schools"] = schools
    aggregate["supplementalCheckedAt"] = report["checkedAt"]
    aggregate["nsysuSupplementalCourseCount"] = report["verifiedCourses"]
    aggregate["nsysuSupplementalInstructorCount"] = report["publishedCourseInstructorCards"]
    base_importer_count = int(
        aggregate.get("baseImporterCourseCount") or aggregate.get("courseCount") or 0
    )
    aggregate["baseImporterCourseCount"] = base_importer_count
    aggregate["courseCount"] = base_importer_count + report["verifiedCourses"]
    aggregate["publishedCourseCount"] = aggregate["courseCount"]
    aggregate["nsysuMigrationFiles"] = report["migrationFiles"]
    AGGREGATE_REPORT.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import official NSYSU course history")
    parser.add_argument("--workers", type=int, default=6, help="bounded parallel official-page requests")
    parser.add_argument("--refresh", action="store_true", help="ignore the local official-response cache")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be between 1 and 8")

    CACHE.mkdir(parents=True, exist_ok=True)
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    static_codes = load_static_department_codes(refresh=args.refresh)
    if len(static_codes) < MIN_UNIT_CATALOG_SIZE:
        raise RuntimeError(f"official NSYSU unit catalog is unexpectedly small: {len(static_codes)}")
    source_rows: list[dict] = []
    term_reports: list[dict] = []
    for year, semester in TERMS:
        rows, term_report = load_term(
            year,
            semester,
            workers=args.workers,
            refresh=args.refresh,
            static_codes=static_codes,
        )
        source_rows.extend(rows)
        term_reports.append(term_report)
        print(
            f"NSYSU {year}-{semester}: {len(rows)} offerings from "
            f"{term_report['successfulDepartmentQueries']}/"
            f"{term_report['departmentQueries']} official unit reports",
            flush=True,
        )
        if term_report["failedDepartmentQueries"]:
            failed_codes = ", ".join(
                failure["departmentCode"]
                for failure in term_report["failedDepartmentQueries"][:12]
            )
            raise RuntimeError(
                f"NSYSU {year}-{semester} has failed official unit reports: {failed_codes}"
            )
        if term_report["successfulDepartmentQueries"] != len(static_codes):
            raise RuntimeError(
                f"NSYSU {year}-{semester} did not validate the complete official unit catalog"
            )
        if len(rows) < MIN_OFFERINGS_PER_TERM:
            raise RuntimeError(
                f"NSYSU {year}-{semester} is incomplete: only {len(rows)} parsed offerings"
            )

    active = load_current_official_faculty()
    faculty_page_count = len(active)
    for row in source_rows:
        if row["term"] != CURRENT_TERM:
            continue
        for teacher in row["teachers"]:
            active.setdefault(teacher, {
                "name": teacher,
                "department": row["department"],
                "sourceUrl": row["officialSourceUrl"],
                "evidence": "current-course-report",
            })

    courses, counters = deduplicate(source_rows, active, load_department_sites())
    migration_files = write_migrations(courses, checked_at)
    available_terms = [
        report["term"]
        for report in term_reports
        if report["successfulDepartmentQueries"] == len(static_codes)
        and report["parsedOfferings"] >= MIN_OFFERINGS_PER_TERM
    ]
    failed_queries = [
        {"term": report["term"], **failure}
        for report in term_reports
        for failure in report["failedDepartmentQueries"]
    ]
    card_count = sum(len(course["instructors"]) for course in courses)
    report_payload = {
        "policy": {
            "officialUniversityDomainsOnly": True,
            "captchaBypassed": False,
            "requiresCurrentOfficialInstructorEvidence": True,
            "inactiveOrUnverifiedInstructorsPublished": False,
            "specialResearchCoursesExcluded": True,
            "failClosedResponseValidation": True,
            "completeStaticUnitCatalogPerTerm": True,
        },
        "checkedAt": checked_at,
        "universityId": UNIVERSITY_ID,
        "status": "imported",
        "officialIndex": OFFICIAL_COURSE_INDEX,
        "officialReportEndpoint": COURSE_REPORT_ENDPOINT,
        "sourceFormat": "official HTML course handbook report (PRTCRS=2)",
        "earliestAcademicYear": EARLIEST_YEAR,
        "latestAcademicYear": CURRENT_YEAR,
        "unitCatalogCount": len(static_codes),
        "minimumOfferingsPerTerm": MIN_OFFERINGS_PER_TERM,
        "availableTerms": available_terms,
        "missingTerms": [f"{year}-{semester}" for year, semester in TERMS if f"{year}-{semester}" not in available_terms],
        "parsedOfferings": len(source_rows),
        "verifiedHistoricalOfferings": counters["verifiedHistoricalOfferings"],
        "verifiedCourses": len(courses),
        "publishedCourseInstructorCards": card_count,
        "publishedDepartments": len({course["department"] for course in courses}),
        "activeInstructorCount": len(active),
        "activeFacultyPageCount": faculty_page_count,
        "activeCourseReportEvidenceCount": sum(1 for row in active.values() if row["evidence"] == "current-course-report"),
        "rejectedWithoutCurrentInstructor": counters["rejectedWithoutCurrentInstructor"],
        "excludedSpecialResearch": counters["excludedSpecialResearch"],
        "departmentQueries": sum(report["departmentQueries"] for report in term_reports),
        "successfulDepartmentQueries": sum(
            report["successfulDepartmentQueries"] for report in term_reports
        ),
        "emptyDepartmentQueries": sum(report["emptyDepartmentQueries"] for report in term_reports),
        "failedDepartmentQueries": failed_queries,
        "terms": term_reports,
        "migrationFiles": migration_files,
    }
    REPORT.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_aggregate_course_report(report_payload)
    print(json.dumps({
        "courses": len(courses),
        "cards": card_count,
        "activeInstructors": len(active),
        "migrations": migration_files,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
