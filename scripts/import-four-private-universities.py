"""Import official course data for CYCU, TKU, YZU, and FCU.

Only university-owned public systems are queried. Historical offerings are
kept only when the instructor also appears in the school's current public
course roster. The generated D1 migrations intentionally collapse academic
years while preserving the upper/lower-semester distinction required by the
product UI.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import http.cookiejar
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".four-school-course-cache"
DRIZZLE = ROOT / "drizzle"
REPORT_PATH = ROOT / "db" / "four-school-course-report.generated.json"
CURRENT_TERM = "1151"
GENERATED_AT = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

OFFICIAL_INDEX = {
    "cycu": "https://itouch.cycu.edu.tw/active_system/CourseQuerySystem/spa/",
    "tku": "https://esquery.tku.edu.tw/acad/upload/",
    "yzu": "https://portalfun.yzu.edu.tw/cosSelect/index.aspx?D=G",
    "fcu": "https://coursesearch04.fcu.edu.tw/",
}

OFFICIAL_DEPARTMENT_DIRECTORIES = {
    "cycu": "https://www.cycu.edu.tw/?page_id=2399",
    "tku": "https://www.tku.edu.tw/tku/?page_id=4807",
    "yzu": "https://www.yzu.edu.tw/index.php/tw/academics",
    "fcu": "https://www.fcu.edu.tw/organization/cof-units/",
}

OFFICIAL_SUFFIXES = {
    "cycu": ("cycu.edu.tw",),
    "tku": ("tku.edu.tw",),
    "yzu": ("yzu.edu.tw",),
    "fcu": ("fcu.edu.tw",),
}

GENERIC_INSTRUCTORS = {
    "助教", "待聘", "待聘教師", "指導教授", "授課教師", "教師", "老師",
    "專任教師", "兼任教師", "未定", "無", "none", "staff", "teacher",
}

_write_lock = threading.Lock()


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def sql_text(value: object) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def stable_id(prefix: str, *parts: object, length: int = 18) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


def official_url(school: str, value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not any(
        host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_SUFFIXES[school]
    ):
        raise ValueError(f"Rejected non-official URL for {school}: {value}")
    return value


def clean_department(value: object) -> str:
    text = normalize_space(value).strip("　-—:：")
    text = re.sub(r"^[A-Z0-9]{3,8}[.．]", "", text)
    return text[:100] or "其他教學單位"


def clean_course_name(value: object) -> str:
    text = normalize_space(value).strip("　-—:：")
    text = re.split(r"(?:◇|限本系|本課程|本科目|淡江大學智慧|<)" , text, maxsplit=1)[0].strip()
    return text[:160]


DEPARTMENT_ALIASES = {
    "企管": "企業管理",
    "應外": "應用外國語文",
    "商設": "商業設計",
    "醫工": "生物醫學工程",
    "資管": "資訊管理",
    "國貿": "國際經營與貿易",
    "資訊": "資訊工程",
    "資工": "資訊工程",
    "資傳": "資訊傳播",
    "環工": "環境工程",
    "應數": "應用數學",
    "財法": "財經法律",
    "特教": "特殊教育",
    "室設": "室內設計",
    "財金": "財務金融",
    "生科": "生物科技",
    "宗研": "宗教",
    "教研": "教育",
    "師培": "師資培育",
    "中文": "中國文學",
    "外文": "外國語文",
    "機電": "機械與電腦輔助工程",
    "環科": "環境工程與科學",
    "自控": "自動控制工程",
    "纖維複材": "纖維與複合材料",
    "通訊": "通訊工程",
    "工工": "工業工程",
    "土管": "土地管理",
    "水利": "水利工程",
    "風保": "風險管理與保險",
    "航太": "航空太空工程",
    "都資": "都市計畫與空間資訊",
    "大傳": "大眾傳播",
    "資圖": "資訊與圖書館",
    "化材": "化學工程與材料工程",
    "水環": "水資源及環境工程",
    "運管": "運輸管理",
    "教科": "教育科技",
    "教設": "教育與未來設計",
    "政經": "全球政治經濟",
    "政法": "公共行政",
}


def normalize_department_identity(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.split(r"\s+[A-Z][A-Z\s’'(),.-]{3,}", text, maxsplit=1)[0]
    text = re.sub(r"(?:碩士|博士|學士)?(?:在職)?(?:專班|班)$", "", text)
    text = re.sub(r"(?:學系|研究所|學位學程|學程|中心|學院|系|所|班|日|進學)$", "", text)
    text = re.sub(r"[一二三四五六七八九十]+$", "", text)
    text = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", text).lower()
    return DEPARTMENT_ALIASES.get(text, text)


class OfficialLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = normalize_space("".join(self._text))
        url = urllib.parse.urljoin(self.base_url, self._href)
        if text and url.startswith("http://"):
            url = "https://" + url[7:]
        if text:
            self.links.append((text, url))
        self._href = None
        self._text = []


def load_official_department_links(school: str) -> list[tuple[str, str]]:
    directory = official_url(school, OFFICIAL_DEPARTMENT_DIRECTORIES[school])
    payload = cached_bytes(
        f"official-departments-{school}.html",
        directory,
        timeout=90,
        minimum_size=500,
    )
    parser = OfficialLinkParser(directory)
    parser.feed(payload.decode("utf-8-sig", errors="replace"))
    links: list[tuple[str, str]] = []
    for name, url in parser.links:
        try:
            source = official_url(school, url)
        except ValueError:
            continue
        path = urllib.parse.urlparse(source).path.lower()
        if re.search(r"\.(?:avif|bmp|docx?|gif|jpe?g|odp|ods|odt|pdf|png|pptx?|rar|svg|webp|xlsx?|zip)$", path):
            continue
        identity = normalize_department_identity(name)
        if len(identity) >= 2 and identity not in {"了解更多", "learnmore", "首頁", "回首頁"}:
            links.append((name, source))
    return links


def resolve_department_url(school: str, department: str, links: list[tuple[str, str]]) -> str:
    target = normalize_department_identity(department)
    ranked: list[tuple[int, int, int, str]] = []
    for name, url in links:
        identity = normalize_department_identity(name)
        score = 1000 if name == department else 900 if identity == target else 700 if min(len(identity), len(target)) >= 2 and (identity in target or target in identity) else 0
        if score:
            ranked.append((score, -len(url), len(identity), url))
    if ranked:
        return max(ranked)[3]
    return official_url(school, OFFICIAL_DEPARTMENT_DIRECTORIES[school])


def split_teachers(value: object) -> list[str]:
    text = normalize_space(value)
    text = re.sub(r"[（(]\s*[0-9* ,，、]+\s*[)）]", "", text)
    text = text.replace("\u3000", " ")
    candidates = re.split(r"[,，、;/；|&＋+]|\s{2,}|\n+", text)
    result: list[str] = []
    for candidate in candidates:
        name = normalize_space(candidate).replace(" ", "")
        name = re.sub(r"(?:教授|副教授|助理教授|講師|老師)$", "", name)
        lowered = name.lower()
        if not name or lowered in GENERIC_INSTRUCTORS or "助教" in name or "待聘" in name:
            continue
        if len(name) < 2 or len(name) > 40 or not re.search(r"[A-Za-z\u3400-\u9fff]", name):
            continue
        if name not in result:
            result.append(name)
    return result


def request_bytes(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
                  timeout: int = 60) -> tuple[bytes, dict[str, str]]:
    request_headers = {
        "User-Agent": "WZUNAA-official-course-audit/2.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        **(headers or {}),
    }
    request = urllib.request.Request(url, data=data, headers=request_headers)
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def cached_bytes(key: str, url: str, *, data: bytes | None = None,
                 headers: dict[str, str] | None = None, timeout: int = 60,
                 minimum_size: int = 20) -> bytes:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / key
    if path.exists() and path.stat().st_size >= minimum_size:
        return path.read_bytes()
    payload, _ = request_bytes(url, data=data, headers=headers, timeout=timeout)
    if len(payload) < minimum_size:
        raise ValueError(f"Official response was unexpectedly small: {url}")
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return payload


def cached_json(key: str, url: str, body: dict[str, object], *,
                headers: dict[str, str] | None = None) -> object:
    payload = cached_bytes(
        key,
        url,
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
        timeout=90,
    )
    return json.loads(payload.decode("utf-8-sig"))


@dataclass
class CourseRecord:
    school: str
    semester: str
    name: str
    department: str
    official_source_url: str
    department_source_url: str
    instructors: dict[str, str] = field(default_factory=dict)
    terms: set[str] = field(default_factory=set)


class CourseCollection:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], CourseRecord] = {}
        self.department_urls: dict[tuple[str, str], str] = {}

    def add(self, *, school: str, term: str, name: object, department: object,
            teachers: object, source_url: str, department_url: str | None = None,
            department_links: list[tuple[str, str]] | None = None,
            active_teachers: set[str] | None = None) -> None:
        course_name = clean_course_name(name)
        if not course_name or "專題研究" in course_name:
            return
        semester = term[-1:] if term[-1:] in {"1", "2"} else ""
        if not semester:
            return
        names = split_teachers(teachers)
        if active_teachers is not None:
            names = [teacher for teacher in names if teacher in active_teachers]
        if not names:
            return
        dept = clean_department(department)
        source = official_url(school, source_url)
        department_key = (school, dept)
        if department_url:
            dept_source = official_url(school, department_url)
        else:
            dept_source = self.department_urls.get(department_key) or official_url(
                school,
                resolve_department_url(school, dept, department_links or []),
            )
            self.department_urls[department_key] = dept_source
        key = (school, semester, dept, course_name)
        record = self.records.setdefault(key, CourseRecord(
            school=school,
            semester=semester,
            name=course_name,
            department=dept,
            official_source_url=source,
            department_source_url=dept_source,
        ))
        record.terms.add(term)
        for teacher in names:
            record.instructors[teacher] = source

    def extend(self, other: "CourseCollection") -> None:
        for record in other.records.values():
            for teacher, source_url in record.instructors.items():
                for term in record.terms:
                    self.add(
                        school=record.school,
                        term=term,
                        name=record.name,
                        department=record.department,
                        teachers=teacher,
                        source_url=source_url,
                        department_url=record.department_source_url,
                    )


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag.lower() == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(normalize_space("".join(self._cell)))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def parse_rows(payload: bytes) -> tuple[str, list[list[str]]]:
    text = payload.decode("utf-8-sig", errors="replace")
    parser = TableParser()
    parser.feed(text)
    return text, parser.rows


def import_cycu() -> tuple[CourseCollection, dict[str, object]]:
    school = "cycu"
    base = "https://itouch.cycu.edu.tw/active_system/CourseQuerySystem/mvc/courseQuery.jsp"
    cycu_headers = {
        "Origin": "https://itouch.cycu.edu.tw",
        "Referer": "https://itouch.cycu.edu.tw/active_system/CourseQuerySystem/spa/",
    }
    years_payload = cached_json("cycu-years.json", base + "?method=query", {}, headers=cycu_headers)
    years = years_payload.get("yearTermList", []) if isinstance(years_payload, dict) else []
    selected = [row for row in years if re.fullmatch(r"(?:10[6-9]|11[0-5])[12]", str(row.get("YEAR_TERM", "")))]

    def fetch(row: dict[str, object]) -> tuple[str, list[dict[str, object]]]:
        term = str(row["YEAR_TERM"])
        option = {
            "label": row.get("YEAR_NAME", term),
            "value": term,
            "isGeneralTime": row.get("IS_GENERAL_TIME", "N"),
            "elective_lock": row.get("ELECTIVE_LOCK", "N"),
            "ISSELCOURSETIME": row.get("ISSELCOURSETIME", "N"),
        }
        result = cached_json(
            f"cycu-{term}.json",
            base + "?method=getCourseData",
            {
                "YEAR_TERM": option,
                "elective_lock": option["elective_lock"],
                "locale": "zh-TW",
                "ISSELCOURSETIME": option["ISSELCOURSETIME"],
            },
            headers=cycu_headers,
        )
        rows = result.get("datas", []) if isinstance(result, dict) else []
        return term, rows if isinstance(rows, list) else []

    offerings: dict[str, list[dict[str, object]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for term, rows in pool.map(fetch, selected):
            offerings[term] = rows

    active = {
        teacher
        for row in offerings.get(CURRENT_TERM, [])
        for teacher in split_teachers(row.get("TEACHER_CNAME", ""))
    }
    department_links = load_official_department_links(school)
    courses = CourseCollection()
    for term, rows in offerings.items():
        for row in rows:
            courses.add(
                school=school,
                term=term,
                name=row.get("CURS_NM_C_S"),
                department=row.get("AUTHORITY_NAME") or row.get("ADMIN_DEPT_NAME") or row.get("DEPT_ABVI_C"),
                teachers=row.get("TEACHER_CNAME"),
                source_url=OFFICIAL_INDEX[school],
                department_links=department_links,
                active_teachers=active,
            )
    return courses, {
        "officialIndex": OFFICIAL_INDEX[school],
        "coverage": f"{min(offerings)}-{max(offerings)}" if offerings else "none",
        "rawOfferings": sum(len(rows) for rows in offerings.values()),
        "activeInstructors": len(active),
    }


def import_fcu() -> tuple[CourseCollection, dict[str, object]]:
    school = "fcu"
    base = "https://coursesearch04.fcu.edu.tw/Service/Search.asmx/"
    degrees = ("1", "3", "4", "5")
    terms = [(year, semester) for year in range(107, 115) for semester in (1, 2)] + [(115, 1)]
    department_lists: dict[str, list[dict[str, object]]] = {}
    unit_names: dict[str, str] = {}
    for degree in degrees:
        body = {"baseOptions": {"lang": "cht", "year": 115, "sms": 1}, "degree": degree}
        result = cached_json(f"fcu-depts-{degree}.json", base + "GetDeptList", body)
        rows = result if isinstance(result, list) else []
        department_lists[degree] = [row for row in rows if isinstance(row, dict) and row.get("id")]
        for department in department_lists[degree]:
            dept_id = str(department["id"])
            units = cached_json(
                f"fcu-units-{degree}-{dept_id}.json",
                base + "GetUnitList",
                {**body, "deptId": dept_id},
            )
            for unit in units if isinstance(units, list) else []:
                if isinstance(unit, dict) and unit.get("id"):
                    unit_names[str(unit["id"])] = clean_department(unit.get("name"))

    jobs = [
        (year, semester, degree, str(department["id"]), clean_department(department.get("name")))
        for year, semester in terms
        for degree in degrees
        for department in department_lists[degree]
    ]

    def fetch(job: tuple[int, int, str, str, str]) -> tuple[tuple[int, int, str, str, str], list[dict[str, object]]]:
        year, semester, degree, dept_id, _ = job
        body = {
            "baseOptions": {"lang": "cht", "year": year, "sms": semester},
            "typeOptions": {"degree": degree, "deptId": dept_id, "unitId": "*", "classId": ""},
        }
        result = cached_json(
            f"fcu-{year}{semester}-{degree}-{dept_id}.json",
            base + "GetType1Result",
            body,
        )
        rows = result.get("items", []) if isinstance(result, dict) else []
        return job, rows if isinstance(rows, list) else []

    offerings: dict[tuple[int, int, str, str], tuple[str, list[dict[str, object]]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(fetch, job) for job in jobs]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            job, rows = future.result()
            year, semester, degree, dept_id, college = job
            offerings[(year, semester, degree, dept_id)] = (college, rows)
            if index % 100 == 0:
                print(f"FCU official queries: {index}/{len(futures)}", flush=True)

    active = {
        teacher
        for (year, semester, _, _), (_, rows) in offerings.items()
        if year == 115 and semester == 1
        for row in rows
        for teacher in split_teachers(row.get("scr_teacher", ""))
    }
    department_links = load_official_department_links(school)
    courses = CourseCollection()
    raw_count = 0
    for (year, semester, _, _), (college, rows) in offerings.items():
        term = f"{year}{semester}"
        raw_count += len(rows)
        for row in rows:
            class_id = str(row.get("cls_id", ""))
            department = unit_names.get(class_id[:4]) or clean_department(row.get("cls_name")) or college
            selector = urllib.parse.quote(str(row.get("scr_selcode", "")))
            outline = f"https://coursesearch04.fcu.edu.tw/CourseOutline.aspx?lang=cht&courseid={term}{selector}"
            courses.add(
                school=school,
                term=term,
                name=row.get("sub_name"),
                department=department,
                teachers=row.get("scr_teacher"),
                source_url=outline,
                department_links=department_links,
                active_teachers=active,
            )
    return courses, {
        "officialIndex": OFFICIAL_INDEX[school],
        "coverage": "1071-1151",
        "rawOfferings": raw_count,
        "officialQueries": len(jobs),
        "activeInstructors": len(active),
    }


def import_tku() -> tuple[CourseCollection, dict[str, object]]:
    school = "tku"
    index = cached_bytes("tku-CourseIndex.html", OFFICIAL_INDEX[school], timeout=90, minimum_size=1000)
    index_text = index.decode("utf-8-sig", errors="replace")
    code_labels: dict[str, str] = {}
    for raw in re.findall(r'new Option\("([^"\r\n]+)', index_text):
        code = raw[:5].replace("_", " ").strip()
        if code not in {"INDEX", "UPNEW"} and re.fullmatch(r"[A-Z0-9]{3,5}", code):
            code_labels[code] = raw.split("_", 1)[-1]

    def fetch(item: tuple[str, str]) -> tuple[str, str, bytes | None]:
        code, label = item
        url = f"https://esquery.tku.edu.tw/acad/upload/data/{code}.htm"
        try:
            return code, label, cached_bytes(f"tku-{code}.html", url, timeout=60, minimum_size=100)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
            return code, label, None

    pages: list[tuple[str, str, bytes]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        for code, label, payload in pool.map(fetch, code_labels.items()):
            if payload:
                pages.append((code, label, payload))

    raw: list[tuple[str, str, str, str]] = []
    for code, label, payload in pages:
        _, rows = parse_rows(payload)
        department = clean_department(label)
        source_url = f"https://esquery.tku.edu.tw/acad/upload/data/{code}.htm"
        for cells in rows:
            joined = " ".join(cells)
            if "系別(Department)" in joined:
                department_match = re.search(r"系別\(Department\)[：:]\s*(?:[A-Z0-9]+[.．])?(.+?)(?:DEPARTMENT|$)", joined, re.I)
                if department_match:
                    department = clean_department(department_match.group(1))
                continue
            if len(cells) < 13 or not re.fullmatch(r"\d+", cells[0].strip()):
                continue
            name = clean_course_name(cells[10])
            teacher = cells[12]
            if name and split_teachers(teacher):
                raw.append((department, name, teacher, source_url))

    active = {teacher for _, _, names, _ in raw for teacher in split_teachers(names)}
    department_links = load_official_department_links(school)
    courses = CourseCollection()
    for department, name, teachers, source_url in raw:
        courses.add(
            school=school,
            term=CURRENT_TERM,
            name=name,
            department=department,
            teachers=teachers,
            source_url=source_url,
            department_links=department_links,
            active_teachers=active,
        )
    return courses, {
        "officialIndex": OFFICIAL_INDEX[school],
        "coverage": "1151 (the university's public offline snapshot)",
        "rawOfferings": len(raw),
        "officialPages": len(pages),
        "activeInstructors": len(active),
        "note": "Older public snapshots are distributed as RAR downloads; only the directly auditable current snapshot is imported.",
    }


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: dict[str, str] = {}
        self.options: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._select = ""
        self._option_value: str | None = None
        self._option_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "input" and values.get("name", "").startswith("__"):
            self.hidden[values["name"]] = values.get("value") or ""
        elif tag.lower() == "select":
            self._select = values.get("name") or ""
        elif tag.lower() == "option" and self._select:
            self._option_value = values.get("value") or ""
            self._option_text = []

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "option" and self._select and self._option_value is not None:
            self.options[self._select].append((self._option_value, normalize_space("".join(self._option_text))))
            self._option_value = None
        elif tag.lower() == "select":
            self._select = ""


def yzu_query(term: str, department: str, *, timeout: int = 45) -> bytes:
    school = "yzu"
    key = f"yzu-{term}-{department}.html"
    path = CACHE / key
    if path.exists() and path.stat().st_size > 1000:
        return path.read_bytes()
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    request = urllib.request.Request(OFFICIAL_INDEX[school], headers={
        "User-Agent": "WZUNAA-official-course-audit/2.0 (+https://map.scmwcscr.com)",
    })
    with opener.open(request, timeout=timeout) as response:
        page = response.read()
    form = FormParser()
    form.feed(page.decode("utf-8-sig", errors="replace"))
    year, semester = term[:3], term[3:]
    body = {
        **form.hidden,
        "Q": "RadioButton1",
        "DDL_YM": f"{year},{semester}  ",
        "DDL_Dept": department,
        "DDL_Degree": "0",
        "Button1": "確定",
    }
    post = urllib.request.Request(
        OFFICIAL_INDEX[school],
        data=urllib.parse.urlencode(body).encode("utf-8"),
        headers={
            "User-Agent": "WZUNAA-official-course-audit/2.0 (+https://map.scmwcscr.com)",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": OFFICIAL_INDEX[school],
        },
    )
    with opener.open(post, timeout=timeout) as response:
        payload = response.read()
    with _write_lock:
        CACHE.mkdir(exist_ok=True)
        path.write_bytes(payload)
    return payload


def import_yzu() -> tuple[CourseCollection, dict[str, object]]:
    school = "yzu"
    base = cached_bytes("yzu-index.html", OFFICIAL_INDEX[school], timeout=90, minimum_size=1000)
    form = FormParser()
    form.feed(base.decode("utf-8-sig", errors="replace"))
    departments = []
    for value, label in form.options.get("DDL_Dept", []):
        label = clean_department(label)
        if value and label and (label.startswith("　") is False):
            departments.append((value, label))
    # The official system is legacy ASP.NET and can be slow. Query current
    # departments concurrently, then attempt history only for successful units.
    current_pages: list[tuple[str, str, bytes]] = []

    def fetch_current(item: tuple[str, str]) -> tuple[str, str, bytes | None]:
        value, label = item
        try:
            return value, label, yzu_query(CURRENT_TERM, value)
        except Exception as error:  # retain a transparent partial-coverage report
            print(f"YZU current query skipped {value}: {error}", flush=True)
            return value, label, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for value, label, payload in pool.map(fetch_current, departments):
            if payload:
                current_pages.append((value, label, payload))

    def extract(page: bytes, fallback_department: str) -> list[tuple[str, str, str, str]]:
        _, rows = parse_rows(page)
        result: list[tuple[str, str, str, str]] = []
        header: dict[str, int] = {}
        for cells in rows:
            joined = " ".join(cells)
            if "課名" in joined or "課程名稱" in joined:
                for index, cell in enumerate(cells):
                    if "課號" in cell or "科號" in cell:
                        header["code"] = index
                    elif "課名" in cell or "課程名稱" in cell:
                        header["name"] = index
                    elif "教師" in cell:
                        header["teacher"] = index
                    elif "系所" in cell or "開課單位" in cell:
                        header["department"] = index
                continue
            if "name" not in header or "teacher" not in header:
                continue
            if len(cells) <= max(header.values()):
                continue
            name = cells[header["name"]]
            teachers = cells[header["teacher"]]
            department = cells[header.get("department", -1)] if "department" in header else fallback_department
            code = cells[header.get("code", -1)] if "code" in header else ""
            if clean_course_name(name) and split_teachers(teachers):
                source = f"https://portalfun.yzu.edu.tw/VC2/GuestX/Cos_Plan.aspx?c=A&id={urllib.parse.quote(code)}&s=1&y=115"
                result.append((department, name, teachers, source))
        return result

    current_rows = [row for _, label, page in current_pages for row in extract(page, label)]
    active = {teacher for _, _, names, _ in current_rows for teacher in split_teachers(names)}
    department_links = load_official_department_links(school)
    courses = CourseCollection()
    for department, name, teachers, source in current_rows:
        courses.add(
            school=school,
            term=CURRENT_TERM,
            name=name,
            department=department,
            teachers=teachers,
            source_url=source,
            department_links=department_links,
            active_teachers=active,
        )
    return courses, {
        "officialIndex": OFFICIAL_INDEX[school],
        "coverage": "1151 (legacy official query; successful public units only)",
        "rawOfferings": len(current_rows),
        "successfulOfficialUnits": len(current_pages),
        "requestedOfficialUnits": len(departments),
        "activeInstructors": len(active),
        "note": "The official legacy ASP.NET service does not provide a stable bulk endpoint; no non-university mirror is used.",
    }


def build_sql(courses: CourseCollection) -> list[str]:
    schools = sorted({record.school for record in courses.records.values()})
    school_list = ", ".join(sql_text(school) for school in schools)
    statements = [
        "-- Generated from university-owned public course systems only.",
        "DELETE FROM course_ratings WHERE course_id IN (SELECT id FROM courses WHERE name LIKE '%專題研究%');",
        "DELETE FROM courses WHERE name LIKE '%專題研究%';",
        f"DELETE FROM course_ratings WHERE course_id IN (SELECT id FROM courses WHERE university_id IN ({school_list}) AND source_type = 'official');",
        f"DELETE FROM courses WHERE university_id IN ({school_list}) AND source_type = 'official';",
    ]
    departments: dict[tuple[str, str], str] = {}
    for record in courses.records.values():
        departments[(record.school, record.department)] = record.department_source_url
    for (school, department), source_url in sorted(departments.items()):
        department_id = stable_id(f"dept-{school}", school, department)
        unit_type = "program" if "學程" in department else "institute" if "所" in department and "系" not in department else "department"
        statements.append(
            "INSERT INTO academic_departments "
            "(id, university_id, college, name, unit_type, official_source_url, created_at, updated_at) VALUES "
            f"({sql_text(department_id)}, {sql_text(school)}, '校內教學單位', {sql_text(department)}, {sql_text(unit_type)}, "
            f"{sql_text(source_url)}, {sql_text(GENERATED_AT)}, {sql_text(GENERATED_AT)}) "
            "ON CONFLICT(university_id, name) DO UPDATE SET official_source_url = excluded.official_source_url, "
            "updated_at = excluded.updated_at;"
        )
    for record in sorted(courses.records.values(), key=lambda item: (item.school, item.semester, item.department, item.name)):
        course_id = stable_id(f"course-{record.school}", record.school, record.semester, record.department, record.name)
        code = "OFFICIAL-" + hashlib.sha256(course_id.encode("utf-8")).hexdigest()[:14].upper()
        terms = sorted(record.terms)
        statements.append(
            "INSERT INTO courses (id, university_id, term, first_term, last_term, offered_terms, semester, "
            "course_code, name, department, official_source_url, department_source_url, source_type, "
            "submitted_by_user_id, created_at, updated_at) VALUES "
            f"({sql_text(course_id)}, {sql_text(record.school)}, {sql_text('official-' + record.semester)}, "
            f"{sql_text(terms[0])}, {sql_text(terms[-1])}, {sql_text(','.join(terms))}, {sql_text(record.semester)}, "
            f"{sql_text(code)}, {sql_text(record.name)}, {sql_text(record.department)}, "
            f"{sql_text(record.official_source_url)}, {sql_text(record.department_source_url)}, 'official', NULL, "
            f"{sql_text(GENERATED_AT)}, {sql_text(GENERATED_AT)});"
        )
        for instructor, source_url in sorted(record.instructors.items()):
            statements.append(
                "INSERT INTO course_instructors (course_id, instructor_name, professor_id, official_source_url, created_at) VALUES "
                f"({sql_text(course_id)}, {sql_text(instructor)}, NULL, {sql_text(source_url)}, {sql_text(GENERATED_AT)});"
            )
    return statements


def write_migrations(statements: list[str], max_bytes: int = 875_000) -> list[Path]:
    for path in DRIZZLE.glob("00??_four_private_universities_part_*.sql"):
        path.unlink()
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for statement in statements:
        encoded = len((statement + "\n").encode("utf-8"))
        if current and size + encoded > max_bytes:
            chunks.append(current)
            current = []
            size = 0
        current.append(statement)
        size += encoded
    if current:
        chunks.append(current)
    paths = []
    for index, chunk in enumerate(chunks, 1):
        migration_number = 24 + index
        path = DRIZZLE / f"{migration_number:04d}_four_private_universities_part_{index:02d}.sql"
        path.write_text("\n".join(chunk) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schools", default="cycu,tku,yzu,fcu")
    args = parser.parse_args()
    selected = [value.strip() for value in args.schools.split(",") if value.strip()]
    importers = {"cycu": import_cycu, "tku": import_tku, "yzu": import_yzu, "fcu": import_fcu}
    unknown = sorted(set(selected) - set(importers))
    if unknown:
        raise SystemExit(f"Unknown schools: {', '.join(unknown)}")
    all_courses = CourseCollection()
    report: dict[str, object] = {"generatedAt": GENERATED_AT, "sourcePolicy": "official university domains only", "schools": {}}
    for school in selected:
        print(f"Importing {school} from {OFFICIAL_INDEX[school]}", flush=True)
        courses, school_report = importers[school]()
        all_courses.extend(courses)
        school_report["courseRows"] = len(courses.records)
        school_report["teacherCards"] = sum(len(record.instructors) for record in courses.records.values())
        report["schools"][school] = school_report
        print(f"{school}: {school_report['courseRows']} courses / {school_report['teacherCards']} teacher cards", flush=True)
    if set(selected) != set(importers):
        raise SystemExit("Generate all four schools together so the replacement migration remains complete.")
    statements = build_sql(all_courses)
    paths = write_migrations(statements)
    report["migrationFiles"] = [path.name for path in paths]
    report["totalCourseRows"] = len(all_courses.records)
    report["totalTeacherCards"] = sum(len(record.instructors) for record in all_courses.records.values())
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
