"""Import audited place-name public universities from official course systems.

Only university-owned public endpoints are accepted. Current-term schedules are
used as the current-affiliation roster, and historical rows are retained only
when at least one instructor is still present in that roster.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import html
import http.cookiejar
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".place-course-cache"
DB = ROOT / "db"
MIGRATIONS = ROOT / "drizzle"
EARLIEST_YEAR = 106
CURRENT_YEAR = 115
TERMS = tuple(f"{year}{semester}" for year in range(EARLIEST_YEAR, CURRENT_YEAR) for semester in (1, 2)) + (f"{CURRENT_YEAR}1",)
BATCH_ID = "place_name_course_batch_01"
CURRENT_CACHE_MAX_AGE_SECONDS = 6 * 60 * 60
NUK_PARTS = ("F", "A", "M", "L", "J", "E", "K", "D", "C")

SCHOOLS = {
    "nfu": {
        "name": "國立虎尾科技大學",
        "shortName": "虎科大",
        "city": "雲林縣",
        "district": "虎尾鎮",
        "latitude": 23.7026,
        "longitude": 120.4291,
        "address": "雲林縣虎尾鎮文化路64號",
        "hostSuffix": "nfu.edu.tw",
        "index": "https://tqas.nfu.edu.tw/course_schedule",
    },
    "ncue": {
        "name": "國立彰化師範大學",
        "shortName": "彰師大",
        "city": "彰化縣",
        "district": "彰化市",
        "latitude": 24.0816,
        "longitude": 120.5587,
        "address": "彰化縣彰化市進德路1號",
        "hostSuffix": "ncue.edu.tw",
        "index": "https://webapt.ncue.edu.tw/deanv2/other/ob010",
    },
    "nknu": {
        "name": "國立高雄師範大學",
        "shortName": "高師大",
        "city": "高雄市",
        "district": "苓雅區",
        "latitude": 22.6265,
        "longitude": 120.3208,
        "address": "高雄市苓雅區和平一路116號",
        "hostSuffix": "nknu.edu.tw",
        "index": "https://sso.nknu.edu.tw/Stu/scheduleSubject.aspx",
    },
    "ncyu": {
        "name": "國立嘉義大學",
        "shortName": "嘉大",
        "city": "嘉義市",
        "district": "東區",
        "latitude": 23.4632,
        "longitude": 120.4837,
        "address": "嘉義市東區學府路300號",
        "hostSuffix": "ncyu.edu.tw",
        "index": "https://web085003.adm.ncyu.edu.tw/pub_course.aspx",
    },
    "ntnu": {
        "name": "國立臺灣師範大學",
        "shortName": "臺師大",
        "city": "臺北市",
        "district": "大安區",
        "latitude": 25.0261,
        "longitude": 121.5275,
        "address": "臺北市大安區和平東路一段162號",
        "hostSuffix": "ntnu.edu.tw",
        "index": "https://courseap.itc.ntnu.edu.tw/acadmOpenCourse/index.jsp",
    },
    "ntcu": {
        "name": "國立臺中教育大學",
        "shortName": "臺中教大",
        "city": "臺中市",
        "district": "西區",
        "latitude": 24.1451,
        "longitude": 120.6717,
        "address": "臺中市西區民生路140號",
        "hostSuffix": "ntcu.edu.tw",
        "index": "https://ecsa.ntcu.edu.tw/pub/TchSchedule_Search.aspx",
    },
    "ntue": {
        "name": "國立臺北教育大學",
        "shortName": "國北教大",
        "city": "臺北市",
        "district": "大安區",
        "latitude": 25.0244,
        "longitude": 121.5446,
        "address": "臺北市大安區和平東路二段134號",
        "hostSuffix": "ntue.edu.tw",
        "index": "https://nsa.ntue.edu.tw/b09/b09120",
    },
    "ntou": {
        "name": "國立臺灣海洋大學",
        "shortName": "海大",
        "city": "基隆市",
        "district": "中正區",
        "latitude": 25.1505,
        "longitude": 121.7759,
        "address": "基隆市中正區北寧路2號",
        "hostSuffix": "ntou.edu.tw",
        "index": "https://academic.ntou.edu.tw/p/412-1005-1126.php?Lang=zh-tw",
    },
    "ntpu": {
        "name": "國立臺北大學",
        "shortName": "臺北大學",
        "city": "新北市",
        "district": "三峽區",
        "latitude": 24.9450,
        "longitude": 121.3736,
        "address": "新北市三峽區大學路151號",
        "hostSuffix": "ntpu.edu.tw",
        "index": "https://sea.cc.ntpu.edu.tw/pls/dev_stud/course_query_all.CHI_query_common",
    },
    "nptu": {
        "name": "國立屏東大學",
        "shortName": "屏東大學",
        "city": "屏東縣",
        "district": "屏東市",
        "latitude": 22.6653,
        "longitude": 120.5048,
        "address": "屏東縣屏東市民生路4-18號",
        "hostSuffix": "nptu.edu.tw",
        "index": "https://webap.nptu.edu.tw/Web/Secure/default.aspx?SIndex=7",
    },
    "nttu": {
        "name": "國立臺東大學",
        "shortName": "臺東大學",
        "city": "臺東縣",
        "district": "臺東市",
        "latitude": 22.7368,
        "longitude": 121.0677,
        "address": "臺東縣臺東市大學路二段369號",
        "hostSuffix": "nttu.edu.tw",
        "index": "https://infosys.nttu.edu.tw/n_CourseBase_Select/CourseListPublic.aspx",
    },
    "tnua": {
        "name": "國立臺北藝術大學",
        "shortName": "北藝大",
        "city": "臺北市",
        "district": "北投區",
        "latitude": 25.1353,
        "longitude": 121.4692,
        "address": "臺北市北投區學園路1號",
        "hostSuffix": "tnua.edu.tw",
        "index": "https://academic.tnua.edu.tw/academic/course/",
    },
    "tnnua": {
        "name": "國立臺南藝術大學",
        "shortName": "南藝大",
        "city": "臺南市",
        "district": "官田區",
        "latitude": 23.1887,
        "longitude": 120.3733,
        "address": "臺南市官田區大崎里大崎66號",
        "hostSuffix": "tnnua.edu.tw",
        "index": "https://ap.tnnua.edu.tw/CourseInfo/CourseList.aspx",
    },
    "ntub": {
        "name": "國立臺北商業大學",
        "shortName": "北商大",
        "city": "臺北市",
        "district": "中正區",
        "latitude": 25.0422,
        "longitude": 121.5256,
        "address": "臺北市中正區濟南路一段321號",
        "hostSuffix": "ntub.edu.tw",
        "index": "https://ntcbadm.ntub.edu.tw/pub/tchschedule_search.aspx",
    },
    "ntua": {
        "name": "國立臺灣藝術大學",
        "shortName": "臺藝大",
        "city": "新北市",
        "district": "板橋區",
        "latitude": 25.0064,
        "longitude": 121.4487,
        "address": "新北市板橋區大觀路一段59號",
        "hostSuffix": "ntua.edu.tw",
        "index": "https://eec.ntua.edu.tw/Links",
    },
    "ntunhs": {
        "name": "國立臺北護理健康大學",
        "shortName": "北護大",
        "city": "臺北市",
        "district": "北投區",
        "latitude": 25.1182,
        "longitude": 121.5201,
        "address": "臺北市北投區明德路365號",
        "hostSuffix": "ntunhs.edu.tw",
        "index": "https://system10.ntunhs.edu.tw/AcadInfoSystem/Modules/QueryCourse/QueryCourse.aspx",
    },
    "ntus": {
        "name": "國立臺灣體育運動大學",
        "shortName": "臺體大",
        "city": "臺中市",
        "district": "北區",
        "latitude": 24.1487,
        "longitude": 120.6867,
        "address": "臺中市北區雙十路一段16號",
        "hostSuffix": "ntus.edu.tw",
        "index": "https://www.ntus.edu.tw/index.php?act=article&code=list&ids=79",
    },
    "utaipei": {
        "name": "臺北市立大學",
        "shortName": "北市大",
        "city": "臺北市",
        "district": "中正區",
        "latitude": 25.0356,
        "longitude": 121.5137,
        "address": "臺北市中正區愛國西路1號",
        "hostSuffix": "utaipei.edu.tw",
        "index": "https://shcourse.utaipei.edu.tw/utaipei/ag_pro/ag304_index.jsp",
    },
    "nuk": {
        "name": "國立高雄大學",
        "shortName": "高雄大學",
        "city": "高雄市",
        "district": "楠梓區",
        "latitude": 22.7335,
        "longitude": 120.2841,
        "address": "高雄市楠梓區高雄大學路700號",
        "hostSuffix": "nuk.edu.tw",
        "index": "https://course.nuk.edu.tw/QueryCourse/QueryCourse.asp",
    },
    "nkuht": {
        "name": "國立高雄餐旅大學",
        "shortName": "高餐大",
        "city": "高雄市",
        "district": "小港區",
        "latitude": 22.5656,
        "longitude": 120.3727,
        "address": "高雄市小港區松和路1號",
        "hostSuffix": "nkuht.edu.tw",
        "index": "https://classic.nkuht.edu.tw/Pub/PubCur.asp",
    },
    "nkust": {
        "name": "國立高雄科技大學",
        "shortName": "高科大",
        "city": "高雄市",
        "district": "楠梓區",
        "latitude": 22.7247,
        "longitude": 120.3157,
        "address": "高雄市楠梓區海專路142號",
        "hostSuffix": "nkust.edu.tw",
        "index": "https://stdsys.nkust.edu.tw/student/Course/QueryCourse",
    },
    "npu": {
        "name": "國立澎湖科技大學",
        "shortName": "澎科大",
        "city": "澎湖縣",
        "district": "馬公市",
        "latitude": 23.5744,
        "longitude": 119.5813,
        "address": "澎湖縣馬公市六合路300號",
        "hostSuffix": "npu.edu.tw",
        "index": "https://cmap.npu.edu.tw/course-allsearch.asp",
    },
    "npust": {
        "name": "國立屏東科技大學",
        "shortName": "屏科大",
        "city": "屏東縣",
        "district": "內埔鄉",
        "latitude": 22.6439,
        "longitude": 120.6098,
        "address": "屏東縣內埔鄉學府路1號",
        "hostSuffix": "npust.edu.tw",
        "index": "https://course.npust.edu.tw/TMISEng/Course/CourseQuery",
    },
    "nqu": {
        "name": "國立金門大學",
        "shortName": "金門大學",
        "city": "金門縣",
        "district": "金寧鄉",
        "latitude": 24.4480,
        "longitude": 118.3227,
        "address": "金門縣金寧鄉大學路1號",
        "hostSuffix": "nqu.edu.tw",
        "index": "https://ecampus.nqu.edu.tw/CoreCom/Home/Index.aspx",
    },
    "yuntech": {
        "name": "國立雲林科技大學",
        "shortName": "雲科大",
        "city": "雲林縣",
        "district": "斗六市",
        "latitude": 23.6954,
        "longitude": 120.5340,
        "address": "雲林縣斗六市大學路三段123號",
        "hostSuffix": "yuntech.edu.tw",
        "index": "https://webapp.yuntech.edu.tw/webnewcas/course/querycour.aspx",
    },
    "nou": {
        "name": "國立空中大學",
        "shortName": "空中大學",
        "city": "新北市",
        "district": "蘆洲區",
        "latitude": 25.0871,
        "longitude": 121.4659,
        "address": "新北市蘆洲區中正路172號",
        "hostSuffix": "nou.edu.tw",
        "index": "https://nouapp.nou.edu.tw/depys/index",
    },
    "nutn": {
        "name": "國立臺南大學",
        "shortName": "南大",
        "city": "臺南市",
        "district": "中西區",
        "latitude": 22.9846,
        "longitude": 120.2075,
        "address": "臺南市中西區樹林街二段33號",
        "hostSuffix": "nutn.edu.tw",
        "index": "https://academics.nutn.edu.tw/Course/Qry/cos",
    },
    "nutc": {
        "name": "國立臺中科技大學",
        "shortName": "中科大",
        "city": "臺中市",
        "district": "北區",
        "latitude": 24.1492,
        "longitude": 120.6839,
        "address": "臺中市北區三民路三段129號",
        "hostSuffix": "nutc.edu.tw",
        "index": "https://aisap.nutc.edu.tw/public/day/course_list.aspx",
    },
}


class FormAndTableParser(HTMLParser):
    """Extract WebForms hidden state and one result table without dependencies."""

    def __init__(self, table_id: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.hidden: dict[str, str] = {}
        self.inputs: list[dict[str, str]] = []
        self.rows: list[list[dict[str, object]]] = []
        self._table_depth = 0
        self._row: list[dict[str, object]] | None = None
        self._cell: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "input" and values.get("type", "").lower() == "hidden":
            name = values.get("name") or values.get("id")
            if name:
                self.hidden[name] = values.get("value", "")
        if tag == "input":
            self.inputs.append(values)
        if tag == "table":
            if self._table_depth:
                self._table_depth += 1
            elif self.table_id and values.get("id") == self.table_id:
                self._table_depth = 1
            return
        if not self._table_depth:
            return
        if tag == "tr" and self._row is None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None and self._cell is None:
            self._cell = {"text": [], "links": []}
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append("、")
        elif tag == "a" and self._cell is not None:
            link = values.get("href") or values.get("onclick")
            if link:
                self._cell["links"].append(link)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._table_depth:
            return
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append({
                "text": normalize_space(" ".join(self._cell["text"])),
                "links": list(self._cell["links"]),
            })
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1


class DirectTableParser(HTMLParser):
    """Capture only the direct rows/cells of a table while retaining nested link text."""

    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.rows: list[list[dict[str, object]]] = []
        self._table_depth = 0
        self._row: list[dict[str, object]] | None = None
        self._cell: dict[str, object] | None = None
        self._anchor: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "table":
            if self._table_depth:
                self._table_depth += 1
            elif values.get("id") == self.table_id:
                self._table_depth = 1
            return
        if not self._table_depth:
            return
        if tag == "tr" and self._table_depth == 1 and self._row is None:
            self._row = []
        elif tag in {"td", "th"} and self._table_depth == 1 and self._row is not None and self._cell is None:
            self._cell = {"text": [], "links": [], "anchors": []}
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append("、")
            if self._anchor is not None:
                self._anchor["text"].append("、")
        elif tag == "a" and self._cell is not None:
            link = values.get("onclick") or values.get("href")
            anchor = {"href": link, "text": []}
            self._cell["anchors"].append(anchor)
            if link:
                self._cell["links"].append(link)
            self._anchor = anchor
        elif self._cell is not None and values.get("onclick"):
            # TNNUA puts its syllabus action on a span in the course-name cell.
            self._cell["links"].append(values["onclick"])
        elif tag == "div" and self._anchor is not None and any(
            normalize_space(value) for value in self._anchor["text"]
        ):
            self._anchor["text"].append(" ␞ ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
            if self._anchor is not None:
                self._anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._table_depth:
            return
        if tag == "a":
            self._anchor = None
        elif tag in {"td", "th"} and self._table_depth == 1 and self._cell is not None and self._row is not None:
            self._row.append({
                "text": normalize_space(" ".join(self._cell["text"])),
                "links": list(self._cell["links"]),
                "anchors": [
                    {
                        "href": anchor["href"],
                        "text": normalize_space(" ".join(anchor["text"])),
                    }
                    for anchor in self._cell["anchors"]
                ],
            })
            self._cell = None
        elif tag == "tr" and self._table_depth == 1 and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1


def parse_direct_table(payload: bytes, table_id: str, encoding: str = "utf-8") -> list[list[dict[str, object]]]:
    parser = DirectTableParser(table_id)
    parser.feed(payload.decode(encoding, "replace"))
    parser.close()
    return parser.rows


def parse_form_and_table(payload: bytes, table_id: str | None = None) -> FormAndTableParser:
    parser = FormAndTableParser(table_id)
    parser.feed(payload.decode("utf-8", "replace"))
    parser.close()
    return parser


def parse_all_html_rows(payload: bytes, encoding: str = "utf-8") -> list[list[dict[str, object]]]:
    text = payload.decode(encoding, "replace")
    rows = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        cells = []
        for cell_html in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.I | re.S):
            links = []
            for anchor in re.findall(r"<a\b[^>]*>", cell_html, flags=re.I | re.S):
                match = re.search(r"(?:href|onclick)=[\"']([^\"']+)", anchor, flags=re.I)
                if match:
                    links.append(html.unescape(match.group(1)))
            cells.append({"text": strip_html(cell_html), "links": links})
        if cells:
            rows.append(cells)
    return rows


def normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_name(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.sub(r"(?:教授|副教授|助理教授|講師|老師)$", "", text)
    if re.search(r"[A-Za-z]", text):
        return normalize_space(text).strip("、,，;/；")
    return re.sub(r"\s+", "", text).strip("、,，;/；")


def strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "、", value, flags=re.I)
    return normalize_space(re.sub(r"<[^>]+>", " ", value))


def split_instructors(value: object) -> list[str]:
    result = []
    text = str(value or "")
    separator = r"[、,，;/／；\n]+" if re.search(r"[A-Za-z]", text) else r"[\s、,，;/／；]+"
    for raw in re.split(separator, text):
        name = normalize_name(raw)
        if (
            not name
            or not re.search(r"[\u3400-\u9fffA-Za-z]", name)
            or re.search(r"課程|系所|學程|中心|學院|授課|登入|教師|師資|未定|待聘", name)
            or re.search(r"\b(?:staff|tba|unknown)\b", name, flags=re.I)
            or name in {"指導教授", "合授教師", "未定", "待聘", "無", "外校老師", "論文", "專題", "實習"}
            or (re.search(r"[A-Za-z]", name) and not 2 <= len(name) <= 80)
            or (not re.search(r"[A-Za-z]", name) and not 2 <= len(name) <= 8)
        ):
            continue
        if name not in result:
            result.append(name)
    return result


# ``FormAndTableParser`` and ``DirectTableParser`` mark a ``<br>`` inside a cell
# with this token, so a course-name cell that stacks the Chinese name above its
# English translation and its merged-class note arrives as one joined string.
# A real course name never puts whitespace after an enumeration comma, so the
# marker followed by a space is always a line break the school printed.
CELL_LINE_BREAK = re.compile(r"、(?=\s)")
MERGED_CLASS_NOTE = re.compile(r"[（(][^（()）]*(?:另併|合併|併班|合班)[^（()）]*[）)]\s*$")


def official_course_name(value: object) -> str:
    """Publish the official first line of a course-name cell.

    Only the school's own first line is kept: the English translation and the
    merged-class note the schedule prints on later lines are dropped, and no
    text is invented.
    """
    name = CELL_LINE_BREAK.split(normalize_space(value), 1)[0]
    while True:
        trimmed = normalize_space(MERGED_CLASS_NOTE.sub("", name).rstrip("、 "))
        if trimmed == name or not trimmed:
            break
        name = trimmed
    return name


def is_excluded_course(name: object) -> bool:
    text = normalize_space(name).lower()
    return "專題研究" in text or "special research project" in text


def official_url(school_id: str, value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    suffix = SCHOOLS[school_id]["hostSuffix"]
    if parsed.scheme != "https" or not (host == suffix or host.endswith("." + suffix)):
        raise ValueError(f"non-official URL rejected for {school_id}: {value}")
    return value


def cache_filename_is_current(filename: str) -> bool:
    """Return whether a cache object participates in current-roster evidence."""
    term = f"{CURRENT_YEAR}1"
    if re.search(rf"(?:^|[-_]){re.escape(term)}(?:[-_.]|$)", filename, flags=re.I):
        return True
    if re.search(r"(?:^|[-_])current(?:[-_.]|$)", filename, flags=re.I):
        return True
    # NPU publishes both semesters in one academic-year response.
    return filename.lower() == f"npu-{CURRENT_YEAR}-all.html"


def cache_entry_is_reusable(path: Path, filename: str, minimum_size: int) -> bool:
    if not path.exists() or path.stat().st_size < minimum_size:
        return False
    if not cache_filename_is_current(filename):
        return True
    age = max(0.0, time.time() - path.stat().st_mtime)
    return age <= CURRENT_CACHE_MAX_AGE_SECONDS


def cached_request(
    school_id: str,
    filename: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
    minimum_size: int = 100,
) -> bytes:
    official_url(school_id, url)
    CACHE.mkdir(exist_ok=True)
    path = CACHE / filename
    if cache_entry_is_reusable(path, filename, minimum_size):
        return path.read_bytes()
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        **(headers or {}),
    })
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if len(payload) < minimum_size:
                raise ValueError(f"official response is unexpectedly small: {url}")
            path.write_bytes(payload)
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    assert last_error is not None
    raise last_error


def cached_json_request(
    school_id: str,
    filename: str,
    url: str,
    *,
    data: bytes,
    headers: dict[str, str],
    timeout: int = 180,
) -> object:
    payload = cached_request(
        school_id,
        filename,
        url,
        data=data,
        headers=headers,
        timeout=timeout,
        minimum_size=20,
    )
    return json.loads(payload.decode("utf-8-sig"))


def opener_read(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    *,
    timeout: int = 180,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
    assert last_error is not None
    raise last_error


def cached_opener_request(
    school_id: str,
    filename: str,
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 180,
    minimum_size: int = 100,
) -> bytes:
    official_url(school_id, url)
    CACHE.mkdir(exist_ok=True)
    path = CACHE / filename
    if cache_entry_is_reusable(path, filename, minimum_size):
        return path.read_bytes()
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        **(headers or {}),
    })
    payload = opener_read(opener, request, timeout=timeout)
    if len(payload) < minimum_size:
        raise ValueError(f"official response is unexpectedly small: {url}")
    path.write_bytes(payload)
    return payload


def verified_legacy_tls_opener() -> urllib.request.OpenerDirector:
    """Keep certificate verification while allowing older university TLS cipher policy."""
    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


def ensure_webforms_cache(school_id: str, term: str) -> list[Path]:
    """Use the project's TLS-verifying Node runtime for WebForms sites with bot-sensitive POSTs."""
    manifest_path = CACHE / f"{school_id}-{term}-manifest.json"

    def cached_files() -> list[Path]:
        if not cache_entry_is_reusable(manifest_path, manifest_path.name, 1):
            return []
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            count = int(manifest.get("files") or 0)
        except (ValueError, TypeError, json.JSONDecodeError):
            return []
        if school_id == "nknu" and count == 2:
            files = [CACHE / f"nknu-{term}-{division}.html" for division in ("D", "N")]
        elif school_id == "nptu" and count == 1:
            files = [CACHE / f"nptu-{term}.html"]
        elif school_id == "tnnua" and count > 0:
            files = [CACHE / f"tnnua-{term}-{page:03d}.html" for page in range(1, count + 1)]
        else:
            return []
        return files if all(
            cache_entry_is_reusable(path, path.name, 1_000)
            for path in files
        ) else []

    files = cached_files()
    if files:
        return files
    result = subprocess.run(
        ["node", str(ROOT / "scripts" / "fetch-official-webforms.mjs"), school_id, term],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=1_800,
    )
    if result.returncode != 0:
        detail = normalize_space(result.stderr or result.stdout)[:300]
        raise RuntimeError(f"{school_id} official WebForms fetch failed: {detail}")
    files = cached_files()
    if not files:
        raise RuntimeError(f"{school_id} official WebForms fetch produced no verified cache")
    return files


def twca_verified_opener(jar: http.cookiejar.CookieJar) -> urllib.request.OpenerDirector:
    """Build a verified TLS client for school servers that omit the TWCA intermediate."""
    intermediate_url = "https://sslserver.twca.com.tw/cacert/secure_sha2_2023G3.crt"
    intermediate_path = CACHE / "twca-secure-sha2-2023g3.crt"
    if not intermediate_path.exists() or intermediate_path.stat().st_size < 1_000:
        request = urllib.request.Request(intermediate_url, headers={
            "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
        if len(payload) < 1_000:
            raise ValueError("TWCA intermediate certificate is unexpectedly small")
        CACHE.mkdir(exist_ok=True)
        intermediate_path.write_bytes(payload)
    certificate = intermediate_path.read_bytes()
    if certificate.startswith(b"-----BEGIN CERTIFICATE-----"):
        pem = certificate.decode("ascii")
    else:
        pem = ssl.DER_cert_to_PEM_cert(certificate)
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=pem)
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(jar),
    )


NTPU_QUERY = "https://sea.cc.ntpu.edu.tw/pls/dev_stud/course_query_all.queryByAllConditions"
NTPU_EDUCATION_TYPES = ("U", "N", "M", "P")


def ntpu_term_rows(term: str) -> tuple[list[dict], int, list[str]]:
    """Fetch one NTPU term; each degree type returns the complete table in one response."""
    year, semester = term[:3], term[3]

    def fetch_education(education: str) -> list[dict]:
        opener = verified_legacy_tls_opener()
        form = urllib.parse.urlencode({
            "qEdu": education,
            "qCollege": "",
            "qdept": "",
            "qYear": year,
            "qTerm": semester,
            "qGrade": "",
            "qClass": "",
            "cour": "",
            "teach": "",
            "qMemo": "",
            "week": "",
            "seq1": "A",
            "seq2": "M",
        }).encode("ascii")
        payload = cached_opener_request(
            "ntpu",
            f"ntpu-{term}-{education}.html",
            opener,
            NTPU_QUERY,
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://sea.cc.ntpu.edu.tw",
                "Referer": SCHOOLS["ntpu"]["index"],
            },
            timeout=240,
            minimum_size=2_000,
        )
        text = payload.decode("big5", "replace")
        table = re.search(
            r"<table\b[^>]*\bid=[\"']example[\"'][^>]*>(.*?)</table>",
            text,
            flags=re.I | re.S,
        )
        if not table:
            raise ValueError(f"NTPU result table is missing for {term}/{education}")
        rows = []
        for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), flags=re.I | re.S):
            cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.I | re.S)
            if len(cells) < 9:
                continue
            row_year = strip_html(cells[1])
            row_semester = strip_html(cells[2])
            serial = strip_html(cells[3])
            department = strip_html(cells[4])
            name_match = re.search(
                r"<a\b[^>]*href=[\"']([^\"']*course_query\.queryGuide2?[^\"']*)[\"'][^>]*>([^<]+)",
                cells[7],
                flags=re.I | re.S,
            )
            teacher_matches = re.findall(
                r"<a\b[^>]*href=[\"']([^\"']*tec_course_table[^\"']*)[\"'][^>]*>([^<]+)</a>",
                cells[8],
                flags=re.I | re.S,
            )
            if row_year != year or row_semester != semester or not serial or not name_match:
                continue
            name = normalize_space(name_match.group(2))
            if not name or not department or is_excluded_course(name):
                continue
            teacher_sources: dict[str, str] = {}
            for teacher_href, raw_teacher in teacher_matches:
                names = split_instructors(raw_teacher)
                if not names:
                    continue
                teacher = names[0]
                teacher_source = official_url("ntpu", urljoin(NTPU_QUERY, html.unescape(teacher_href)))
                teacher_sources[teacher] = teacher_source
            teachers = list(teacher_sources)
            if not teachers:
                continue
            course_source = official_url("ntpu", urljoin(NTPU_QUERY, html.unescape(name_match.group(1))))
            stable_code = "NTPU-" + hashlib.sha256(
                f"{department}\0{name}".encode("utf-8")
            ).hexdigest()[:16].upper()
            rows.append({
                "universityId": "ntpu",
                "term": f"{year}-{semester}",
                "courseCode": stable_code,
                "name": name,
                "department": department,
                "officialSourceUrl": course_source,
                "departmentSourceUrl": SCHOOLS["ntpu"]["index"],
                "teacherNames": teachers,
                "teacherSourceUrls": teacher_sources,
            })
        if not rows:
            raise ValueError(f"NTPU returned no usable rows for {term}/{education}")
        return rows

    rows: list[dict] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(NTPU_EDUCATION_TYPES)) as executor:
        futures = {
            executor.submit(fetch_education, education): education
            for education in NTPU_EDUCATION_TYPES
        }
        for future in concurrent.futures.as_completed(futures):
            education = futures[future]
            try:
                rows.extend(future.result())
            except Exception as error:  # keep an auditable partial result; never fabricate rows
                errors.append(f"{term}/{education}: {type(error).__name__}")
    return rows, len(NTPU_EDUCATION_TYPES), errors


def import_ntpu() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, queries, errors = ntpu_term_rows(current_term)
    current_teachers = {
        teacher
        for row in current_rows
        for teacher in row["teacherNames"]
    }
    retained = list(current_rows)
    available = [f"{current_term[:3]}-{current_term[3]}"] if current_rows and not errors else []
    missing = [f"{current_term[:3]}-{current_term[3]}"] if errors or not current_rows else []
    rejected = 0
    all_errors = list(errors)
    for term in reversed(TERMS[:-1]):
        term_rows, term_queries, term_errors = ntpu_term_rows(term)
        queries += term_queries
        if term_rows and not term_errors:
            available.append(f"{term[:3]}-{term[3]}")
        else:
            missing.append(f"{term[:3]}-{term[3]}")
        all_errors.extend(term_errors)
        for row in term_rows:
            kept_teachers = [name for name in row["teacherNames"] if name in current_teachers]
            rejected += len(row["teacherNames"]) - len(kept_teachers)
            if not kept_teachers:
                continue
            row["teacherNames"] = kept_teachers
            row["teacherSourceUrls"] = {
                name: row["teacherSourceUrls"][name]
                for name in kept_teachers
            }
            retained.append(row)
    report = {
        "universityId": "ntpu",
        "status": "imported" if not missing else "partial",
        "officialIndex": SCHOOLS["ntpu"]["index"],
        "availableTerms": sorted(available),
        "missingTerms": sorted(set(missing)),
        "officialQueries": queries,
        "parsedOfferings": len(retained),
        "rejectedWithoutCurrentFaculty": rejected,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    if all_errors:
        report["fetchErrors"] = all_errors
    return retained, report


def ntnu_session() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    common_headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    }
    index = official_url("ntnu", SCHOOLS["ntnu"]["index"])
    with opener.open(urllib.request.Request(index, headers=common_headers), timeout=60) as response:
        response.read()
    init_url = official_url(
        "ntnu",
        "https://courseap.itc.ntnu.edu.tw/acadmOpenCourse/CofopdlCtrl?language=chinese",
    )
    with opener.open(urllib.request.Request(init_url, headers={
        **common_headers,
        "Referer": index,
    }), timeout=60) as response:
        response.read()
    return opener


def ntnu_cached_get(
    opener: urllib.request.OpenerDirector,
    filename: str,
    url: str,
    *,
    literal: bool = False,
) -> bytes:
    official_url("ntnu", url)
    CACHE.mkdir(exist_ok=True)
    path = CACHE / filename
    if cache_entry_is_reusable(path, filename, 20):
        return path.read_bytes()
    request = urllib.request.Request(url, headers={
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        "Referer": "https://courseap.itc.ntnu.edu.tw/acadmOpenCourse/CofopdlCtrl?language=chinese",
        "X-Requested-With": "XMLHttpRequest",
    })
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with opener.open(request, timeout=90) as response:
                payload = response.read()
            if len(payload) < 20:
                raise ValueError(f"NTNU response is unexpectedly small: {url}")
            text = payload.decode("utf-8-sig")
            ast.literal_eval(text) if literal else json.loads(text)
            path.write_bytes(payload)
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    assert last_error is not None
    raise last_error


def ntnu_term_rows(term: str) -> tuple[list[dict], int]:
    year, semester = term[:3], term[3]
    opener = ntnu_session()
    department_url = official_url(
        "ntnu",
        "https://courseap.itc.ntnu.edu.tw/acadmOpenCourse/CofnameCtrl?"
        + urllib.parse.urlencode({
            "action": "cof",
            "type": "chn",
            "year": year,
            "term": semester,
        }),
    )
    department_payload = ntnu_cached_get(
        opener,
        f"ntnu-{term}-departments.json",
        department_url,
        literal=True,
    )
    raw_departments = ast.literal_eval(department_payload.decode("utf-8-sig"))
    departments = {
        normalize_space(item[0]): normalize_space(item[1])
        for item in raw_departments
        if isinstance(item, list) and len(item) >= 2 and normalize_space(item[0])
    }
    if not departments:
        raise ValueError(f"NTNU department selector is empty for {term}")

    def fetch_department(item: tuple[str, str]) -> tuple[str, str, list[dict], str]:
        department_code, department_name = item
        query = {
            "action": "showGrid",
            "acadmYear": year,
            "acadmTerm": semester,
            "deptCode": department_code,
            "chn": "",
            "engTeach": "N",
            "clang": "N",
            "moocs": "N",
            "remoteCourse": "N",
            "digital": "N",
            "adsl": "N",
            "zuDept": "",
            "classCode": "",
            "kind": "",
            "generalCore": "",
            "teacher": "",
            "serial_number": "",
            "course_code": "",
            "language": "chinese",
            "start": "0",
            "limit": "99999",
            "page": "1",
        }
        source = official_url(
            "ntnu",
            "https://courseap.itc.ntnu.edu.tw/acadmOpenCourse/CofopdlCtrl?"
            + urllib.parse.urlencode(query),
        )
        payload = ntnu_cached_get(
            opener,
            f"ntnu-{term}-{department_code}.json",
            source,
        )
        response = json.loads(payload.decode("utf-8-sig"))
        raw_rows = response.get("List") if isinstance(response, dict) else None
        if not isinstance(raw_rows, list):
            raise ValueError(f"NTNU course response has no List for {term}/{department_code}")
        expected = int(response.get("Count") or 0)
        if expected != len(raw_rows):
            raise ValueError(
                f"NTNU incomplete response for {term}/{department_code}: {len(raw_rows)}/{expected}"
            )
        return department_code, department_name, raw_rows, source

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_department, sorted(departments.items()))
        for department_code, department_name, raw_rows, source in results:
            for raw in raw_rows:
                name = normalize_space(raw.get("chn_name") or raw.get("eng_name"))
                teachers = split_instructors(raw.get("teacher"))
                code = normalize_space(raw.get("course_code"))
                department = normalize_space(raw.get("dept_chiabbr")) or department_name
                if not name or not code or not teachers or is_excluded_course(name):
                    continue
                rows.append({
                    "universityId": "ntnu",
                    "term": f"{year}-{semester}",
                    "courseCode": code,
                    "name": name,
                    "department": department,
                    "officialSourceUrl": source,
                    "departmentSourceUrl": source,
                    "teacherNames": teachers,
                })
    return rows, len(departments) + 3


def import_ntnu() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntnu_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTNU current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntnu",
        "status": "imported",
        "officialIndex": SCHOOLS["ntnu"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(ntnu_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            verified = []
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                verified.append({**row, "teacherNames": teachers})
            rows.extend(verified)
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    return rows, report


NTOU_OUTSIDE = (
    "https://ais.ntou.edu.tw/outside.aspx?mainPage="
    "LwBBAHAAcABsAGkAYwBhAHQAaQBvAG4ALwBUAEsARQAvAFQASwBFADIAMgAvAFQASwBFADIAMgAxADQAXwAuAGEAcwBwAHgAPwBwAHIAbwBnAGMAZAA9AFQASwBFADIAMgAxADQA"
)
NTOU_QUERY = "https://ais.ntou.edu.tw/Application/TKE/TKE22/TKE2210_01.aspx"


def ntou_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, "DataGrid")
    year, semester = term[:3], term[3]
    rows = []
    for cells in parser.rows:
        if len(cells) < 17:
            continue
        code = normalize_space(cells[2]["text"])
        name = normalize_space(cells[3]["text"])
        department = normalize_space(cells[4]["text"])
        teachers = split_instructors(cells[6]["text"])
        if not code or not name or not teachers or code in {"課號", "科號"} or is_excluded_course(name):
            continue
        rows.append({
            "universityId": "ntou",
            "term": f"{year}-{semester}",
            "courseCode": code,
            "name": name,
            "department": department or "共同課程",
            "officialSourceUrl": NTOU_OUTSIDE,
            "departmentSourceUrl": SCHOOLS["ntou"]["index"],
            "teacherNames": teachers,
        })
    return rows


def ntou_term_rows(term: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ntou-{term}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 5_001):
        payload = cache_path.read_bytes()
        rows = ntou_parse_rows(term, payload)
        if rows:
            return rows, 1

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    common_headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    }
    opener_read(opener, urllib.request.Request(official_url("ntou", NTOU_OUTSIDE), headers=common_headers))
    opener_read(opener, urllib.request.Request(
        official_url("ntou", "https://ais.ntou.edu.tw/Application/TKE/TKE22/TKE2214_.aspx?progcd=TKE2214"),
        headers=common_headers,
    ))
    form_payload = opener_read(opener, urllib.request.Request(
        official_url("ntou", NTOU_QUERY),
        headers=common_headers,
    ))
    parser = parse_form_and_table(form_payload)
    year, semester = term[:3], term[3]
    fields = {
        key: value
        for key, value in parser.hidden.items()
        if key in {"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__VIEWSTATEENCRYPTED", "__EVENTVALIDATION"}
    }
    fields.update({
        "ActivePageControl": "",
        "ColumnFilter": "",
        "SAYEAR": parser.hidden.get("SAYEAR", str(max(int(year) - 1, 81))),
        "QUERY_TYPE": "1",
        "QUERY_COND": "",
        "Q_AYEARSMS": parser.hidden.get("Q_AYEARSMS", f"{CURRENT_YEAR}1"),
        "hidLastTab": "",
        "hdnSelectedTab": "0",
        "Q_AYEAR": year,
        "Q_SMS": semester,
        "Q_DEGREE_CODE": "",
        "Q_FACULTY_CODE": "",
        "Q_GRADE": "",
        "Q_CLASSID": "",
        "radioButtonClass": "0",
        "PC$PageSize": "100000",
        "PC$PageNo": "1",
        "QUERY_BTN1": "查詢",
    })
    payload = opener_read(opener, urllib.request.Request(
        official_url("ntou", NTOU_QUERY),
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            **common_headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://ais.ntou.edu.tw",
            "Referer": NTOU_QUERY,
        },
    ))
    rows = ntou_parse_rows(term, payload)
    if not rows:
        raise ValueError(f"NTOU official response has no courses for {term}")
    CACHE.mkdir(exist_ok=True)
    cache_path.write_bytes(payload)
    return rows, 4


def import_ntou() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntou_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTOU current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntou",
        "status": "imported",
        "officialIndex": SCHOOLS["ntou"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(ntou_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NTUS_OUTSIDE = (
    "https://school.ntus.edu.tw/ntupes/outside.aspx?mainPage="
    "LwBBAHAAcABsAGkAYwBhAHQAaQBvAG4ALwBUAEsARQAvAFQASwBFADUAMAAvAFQASwBFADUAMAAxADAAXwAuAGEAcwBwAHgA"
)
NTUS_QUERY = "https://school.ntus.edu.tw/NTUPES/Application/TKE/TKE50/TKE5010_01.aspx"


def ntus_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, "DataGrid")
    rows = []
    for cells in parser.rows:
        if len(cells) < 16:
            continue
        department = normalize_space(cells[0]["text"])
        code = normalize_space(cells[1]["text"])
        name = normalize_space(cells[2]["text"])
        teachers = split_instructors(cells[12]["text"])
        if not code or not name or not teachers or "課號" in code or is_excluded_course(name):
            continue
        rows.append({
            "universityId": "ntus", "term": f"{term[:3]}-{term[3]}",
            "courseCode": f"{department}:{code}", "name": name,
            "department": department or "共同課程", "officialSourceUrl": NTUS_OUTSIDE,
            "departmentSourceUrl": SCHOOLS["ntus"]["index"], "teacherNames": teachers,
        })
    return rows


def ntus_term_rows(term: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ntus-{term}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 10_001):
        return ntus_parse_rows(term, cache_path.read_bytes()), 1
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5", "Referer": NTUS_QUERY,
    }
    opener_read(opener, urllib.request.Request(official_url("ntus", NTUS_OUTSIDE), headers=headers))
    opener_read(opener, urllib.request.Request(
        official_url("ntus", "https://school.ntus.edu.tw/NTUPES/Application/TKE/TKE50/TKE5010_.aspx"),
        headers=headers,
    ))
    landing = opener_read(opener, urllib.request.Request(official_url("ntus", NTUS_QUERY), headers=headers))
    parser = parse_form_and_table(landing)
    fields = dict(parser.hidden)
    fields.update({
        "ActivePageControl": "", "ColumnFilter": "", "M_PKNO": "", "Mode": "ADD",
        "AYEARSMS": parser.hidden.get("AYEARSMS", term), "ROWSTAMP": "", "TYPE": "",
        "Q_AYEARSMS": term, "OP": "OP1", "Q_FACULTY_CODE": "", "Q_GRADE": "",
        "Q_MUST": "", "QUERY_BTN1": "查  詢", "PC$PageSize": "100000", "PC$PageNo": "1",
        "PC2$PageSize": "100000", "PC2$PageNo": "1", "radioButtonClass": "0",
        "radioButtonQuery": "0",
    })
    payload = opener_read(opener, urllib.request.Request(
        official_url("ntus", NTUS_QUERY), data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = ntus_parse_rows(term, payload)
    if not rows:
        raise ValueError(f"NTUS official response has no courses for {term}")
    CACHE.mkdir(exist_ok=True)
    cache_path.write_bytes(payload)
    return rows, 4


def import_ntus() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntus_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTUS current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntus", "status": "imported", "officialIndex": SCHOOLS["ntus"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"], "missingTerms": [], "officialQueries": current_queries,
        "parsedOfferings": len(current_rows), "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(ntus_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


TNUA_QUERY = "https://selcrs1.tnua.edu.tw/CourseSearch/AdvancedSearch.aspx"
TNUA_ENDPOINT = TNUA_QUERY + "/SearchClass"


def tnua_department_map(page: bytes) -> dict[str, str]:
    text = page.decode("utf-8", "replace")
    select = re.search(
        r'<select[^>]+id=["\']Main_adsearch_semester_selector["\'][^>]*>(.*?)</select>',
        text,
        flags=re.I | re.S,
    )
    if not select:
        raise ValueError("TNUA department selector is unavailable")
    result = {}
    for code, label in re.findall(
        r'<option[^>]+value=["\']([^"\']+)["\'][^>]*>(.*?)</option>',
        select.group(1),
        flags=re.I | re.S,
    ):
        code = normalize_space(code)
        label = strip_html(label)
        if code and label:
            result[code] = re.sub(rf"^{re.escape(code)}-", "", label)
    if not result:
        raise ValueError("TNUA department map is empty")
    return result


def tnua_term_rows(term: str) -> tuple[list[dict], int]:
    jar = http.cookiejar.CookieJar()
    opener = twca_verified_opener(jar)
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5", "Referer": TNUA_QUERY,
    }
    landing = opener_read(opener, urllib.request.Request(official_url("tnua", TNUA_QUERY), headers=headers))
    departments = tnua_department_map(landing)

    def fetch_department(item: tuple[str, str]) -> tuple[str, str, object]:
        code, department = item
        cache_path = CACHE / f"tnua-{term}-{code}.json"
        if cache_entry_is_reusable(cache_path, cache_path.name, 21):
            return code, department, json.loads(cache_path.read_text(encoding="utf-8"))
        body = json.dumps({
            "Year": term[:3], "Term": term[3], "Week": "0", "Sessions": "0", "Sessione": "0",
            "Colnum": code, "Teacher": "", "Classname": "", "Courseid": "", "Englishclass": "0",
        }, ensure_ascii=False).encode()
        payload = opener_read(opener, urllib.request.Request(
            official_url("tnua", TNUA_ENDPOINT), data=body,
            headers={**headers, "Content-Type": "application/json; charset=utf-8", "Origin": "https://selcrs1.tnua.edu.tw"},
        ))
        value = json.loads(payload.decode("utf-8-sig"))
        CACHE.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return code, department, value

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for department_code, department_name, response in executor.map(fetch_department, sorted(departments.items())):
            data = response.get("d") if isinstance(response, dict) else None
            if not isinstance(data, dict):
                raise ValueError(f"TNUA invalid response for {term}/{department_code}")
            status = int(data.get("Status") or 0)
            if status == 2:
                continue
            if status != 0:
                raise ValueError(f"TNUA query failed for {term}/{department_code}: {status}")
            raw_rows = (data.get("ReturnDatas") or {}).get("Class") or []
            for raw in raw_rows:
                name = normalize_space(raw.get("CourseName"))
                code = normalize_space(raw.get("CourseID"))
                teachers = split_instructors(raw.get("Teacher"))
                department = normalize_space(raw.get("DepName")) or department_name
                if re.fullmatch(r"[A-Za-z]*\d+", department):
                    department = department_name
                stable_code = re.sub(r"^\d{4}-", "", code)
                if not name or not code or not teachers or is_excluded_course(name):
                    continue
                rows.append({
                    "universityId": "tnua", "term": f"{term[:3]}-{term[3]}",
                    "courseCode": f"{department_code}:{stable_code}", "name": name, "department": department,
                    "officialSourceUrl": TNUA_QUERY, "departmentSourceUrl": SCHOOLS["tnua"]["index"],
                    "teacherNames": teachers,
                })
    return rows, len(departments) + 1


def import_tnua() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = tnua_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("TNUA current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "tnua", "status": "imported", "officialIndex": SCHOOLS["tnua"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"], "missingTerms": [], "officialQueries": current_queries,
        "parsedOfferings": len(current_rows), "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
        "note": "校方伺服器漏送 TWCA intermediate；匯入器補入官方 CA intermediate 並維持完整 TLS 驗證",
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(tnua_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


def nknu_term_rows(term: str) -> tuple[list[dict], int]:
    rows = []
    for path in ensure_webforms_cache("nknu", term):
        for cells in parse_direct_table(path.read_bytes(), "ctl00_phMain_uScheduleList_uList"):
            if len(cells) != 11 or cells[1]["text"] == "開課代號 / 課程名稱 / 英文名稱":
                continue
            syllabus_anchors = [
                anchor for anchor in cells[1]["anchors"]
                if "syllabusForEnro.aspx" in str(anchor.get("href") or "")
            ]
            code_match = re.match(r"([^\s]+)", str(cells[1]["text"]))
            if not syllabus_anchors or not code_match:
                continue
            code = normalize_space(code_match.group(1))
            name = normalize_space(str(syllabus_anchors[0].get("text") or "").split("␞", 1)[0])
            department = normalize_space(cells[5]["text"])
            teacher_sources = {}
            for anchor in cells[6]["anchors"]:
                if "scheduleTeacher.aspx" not in str(anchor.get("href") or ""):
                    continue
                for teacher in split_instructors(anchor.get("text")):
                    teacher_sources[teacher] = official_url(
                        "nknu",
                        urljoin(SCHOOLS["nknu"]["index"], str(anchor.get("href"))),
                    )
            if not code or not name or not department or not teacher_sources or is_excluded_course(name):
                continue
            course_source = official_url(
                "nknu",
                urljoin(SCHOOLS["nknu"]["index"], str(syllabus_anchors[0].get("href"))),
            )
            department_links = [
                link for link in cells[5]["links"]
                if "scheduleDepartment.aspx" in str(link)
            ]
            department_source = (
                official_url("nknu", urljoin(SCHOOLS["nknu"]["index"], str(department_links[0])))
                if department_links else SCHOOLS["nknu"]["index"]
            )
            rows.append({
                "universityId": "nknu",
                "term": f"{term[:3]}-{term[3]}",
                "courseCode": code,
                "name": name,
                "department": department,
                "officialSourceUrl": course_source,
                "departmentSourceUrl": department_source,
                "teacherNames": list(teacher_sources),
                "teacherSourceUrls": teacher_sources,
            })
    if not rows:
        raise ValueError(f"NKNU returned no usable rows for {term}")
    return rows, 3


def import_nknu() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, queries = nknu_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    retained = list(current_rows)
    available = [f"{current_term[:3]}-{current_term[3]}"]
    missing = []
    errors = []
    rejected = 0
    for term in reversed(TERMS[:-1]):
        try:
            term_rows, term_queries = nknu_term_rows(term)
            queries += term_queries
            available.append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            missing.append(f"{term[:3]}-{term[3]}")
            errors.append(f"{term}: {type(error).__name__}")
            continue
        for row in term_rows:
            teachers = [name for name in row["teacherNames"] if name in current_teachers]
            rejected += len(row["teacherNames"]) - len(teachers)
            if not teachers:
                continue
            row["teacherNames"] = teachers
            row["teacherSourceUrls"] = {name: row["teacherSourceUrls"][name] for name in teachers}
            retained.append(row)
    report = {
        "universityId": "nknu",
        "status": "imported" if not missing else "partial",
        "officialIndex": SCHOOLS["nknu"]["index"],
        "availableTerms": sorted(available),
        "missingTerms": sorted(missing),
        "officialQueries": queries,
        "parsedOfferings": len(retained),
        "rejectedWithoutCurrentFaculty": rejected,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    if errors:
        report["fetchErrors"] = errors
    return retained, report


def tnnua_term_rows(term: str) -> tuple[list[dict], int]:
    rows = []
    files = ensure_webforms_cache("tnnua", term)
    for path in files:
        for cells in parse_direct_table(path.read_bytes(), "MainContent_gv"):
            if len(cells) != 15 or cells[0]["text"] == "開課系所":
                continue
            department = normalize_space(cells[0]["text"])
            raw_code = normalize_space(cells[1]["text"])
            name = re.sub(
                rf"\s*\({term[:3]}[_-]{term[3]}\)\s*$",
                "",
                normalize_space(cells[3]["text"]),
            )
            teachers = split_instructors(cells[12]["text"])
            detail_text = " ".join(str(link) for link in cells[3]["links"])
            detail_match = re.search(
                r"Print_Course_Syllabus\.aspx\?CSN=(\d+)&(?:amp;)?sems=(\d{4})",
                detail_text,
                flags=re.I,
            )
            if (
                not department
                or not raw_code
                or not name
                or not teachers
                or not detail_match
                or detail_match.group(2) != term
                or is_excluded_course(name)
            ):
                continue
            course_source = official_url(
                "tnnua",
                "https://ap.tnnua.edu.tw/CourseInfo/Print_Course_Syllabus.aspx?"
                + urllib.parse.urlencode({"CSN": detail_match.group(1), "sems": detail_match.group(2)}),
            )
            stable_code = "TNNUA-" + hashlib.sha256(
                f"{department}\0{name}".encode("utf-8")
            ).hexdigest()[:16].upper()
            rows.append({
                "universityId": "tnnua",
                "term": f"{term[:3]}-{term[3]}",
                "courseCode": stable_code,
                "name": name,
                "department": department,
                "officialSourceUrl": course_source,
                "departmentSourceUrl": "https://www.tnnua.edu.tw/p/412-1000-91.php?Lang=zh-tw",
                "teacherNames": teachers,
            })
    if not rows:
        raise ValueError(f"TNNUA returned no usable rows for {term}")
    return rows, len(files) + 1


def import_tnnua() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, queries = tnnua_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    retained = list(current_rows)
    available = [f"{current_term[:3]}-{current_term[3]}"]
    missing = []
    errors = []
    rejected = 0
    for term in reversed(TERMS[:-1]):
        try:
            term_rows, term_queries = tnnua_term_rows(term)
            queries += term_queries
            available.append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            missing.append(f"{term[:3]}-{term[3]}")
            errors.append(f"{term}: {type(error).__name__}")
            continue
        for row in term_rows:
            teachers = [name for name in row["teacherNames"] if name in current_teachers]
            rejected += len(row["teacherNames"]) - len(teachers)
            if not teachers:
                continue
            row["teacherNames"] = teachers
            retained.append(row)
    report = {
        "universityId": "tnnua",
        "status": "imported" if not missing else "partial",
        "officialIndex": SCHOOLS["tnnua"]["index"],
        "availableTerms": sorted(available),
        "missingTerms": sorted(missing),
        "officialQueries": queries,
        "parsedOfferings": len(retained),
        "rejectedWithoutCurrentFaculty": rejected,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    if errors:
        report["fetchErrors"] = errors
    return retained, report


def cp950_urlencode(fields: dict[str, object]) -> str:
    return "&".join(
        urllib.parse.quote_from_bytes(str(key).encode("cp950"), safe="")
        + "="
        + urllib.parse.quote_from_bytes(str(value).encode("cp950"), safe="")
        for key, value in fields.items()
    )


def nkuht_class_selector_items(term: str, payload: bytes) -> list[tuple[str, str, str, str]]:
    """Read class + department pairs from the official hierarchical selector."""
    text = payload.decode("cp950", "replace")
    current_department = ""
    classes: list[tuple[str, str, str, str]] = []
    seen = set()
    for paragraph in re.finditer(r"<p\b(?P<attrs>[^>]*)>(?P<body>.*?)</p>", text, flags=re.I | re.S):
        attrs = paragraph.group("attrs")
        body = paragraph.group("body")
        if re.search(r"margin-left\s*:\s*15(?:\.0+)?pt", attrs, flags=re.I):
            heading = strip_html(body)
            if heading and not re.search(r"LoadCur\s*\(", body, flags=re.I):
                current_department = heading
        for match in re.finditer(
            r"LoadCur\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'\)",
            body,
            flags=re.I,
        ):
            year, semester, class_name, team_no, op_class = match.groups()
            if f"{year}{semester}" != term or not op_class:
                continue
            if not current_department:
                raise ValueError(
                    f"NKUHT class selector lacks an official department heading for {term}/{op_class}"
                )
            item = (html.unescape(class_name), current_department, team_no, op_class)
            if item not in seen:
                seen.add(item)
                classes.append(item)
    return classes


def nkuht_parse_page(term: str, department: str, payload: bytes) -> list[dict]:
    text = payload.decode("cp950", "replace")
    rows = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)
        if len(cells) < 10 or not re.fullmatch(r"\d+", strip_html(cells[0])):
            continue
        match = re.search(
            r"TeachingData\('([^']*)','([^']*)','([^']*)','([^']*)','([^']*)'\)",
            row_html,
            flags=re.I,
        )
        if not match:
            continue
        year, semester, op_class, serial, subject_id = match.groups()
        if f"{year}{semester}" != term:
            continue
        name = re.sub(r"\s*\*+\s*$", "", strip_html(cells[2]))
        teachers = [name for name in split_instructors(strip_html(cells[4])) if "�" not in name]
        if not name or not teachers or is_excluded_course(name):
            continue
        source = official_url(
            "nkuht",
            "https://classic.nkuht.edu.tw/Pub/Sel_Teaching.asp?"
            + urllib.parse.urlencode({
                "Years": year,
                "Term": semester,
                "Op_Class": op_class,
                "Serial": serial,
                "Cos_ID": subject_id,
            }),
        )
        rows.append({
            "universityId": "nkuht",
            "term": f"{year}-{semester}",
            "courseCode": f"{department}:{subject_id}",
            "name": name,
            "department": department,
            "officialSourceUrl": source,
            "departmentSourceUrl": "https://www.nkuht.edu.tw/p/404-1000-12427.php?Lang=zh-tw",
            "teacherNames": teachers,
        })
    return rows


def nkuht_class_pages(
    term: str,
    class_name: str,
    department: str,
    team_no: str,
    op_class: str,
) -> tuple[list[dict], int]:
    jar = http.cookiejar.CookieJar()
    opener = twca_verified_opener(jar)
    base = official_url("nkuht", "https://classic.nkuht.edu.tw/Pub/CurDataList.asp")
    fields = {
        "Years": term[:3],
        "Term": term[3],
        "TeamNo": team_no,
        "DeptName": class_name,
        "OpClass": op_class,
    }
    rows = []
    queries = 0
    page = 1
    while True:
        cache_path = CACHE / f"nkuht-{term}-{op_class}-{page:03d}.html"
        if cache_entry_is_reusable(cache_path, cache_path.name, 500):
            payload = cache_path.read_bytes()
        elif page == 1:
            source = base + "?" + cp950_urlencode(fields)
            payload = cached_opener_request(
                "nkuht",
                cache_path.name,
                opener,
                source,
                timeout=180,
                minimum_size=500,
            )
            queries += 1
        else:
            post_fields = {
                **fields,
                "EntryYear": "",
                "Op_Class": op_class,
                "Serial": "",
                "Cos_ID": "",
                "PageNo": page,
            }
            payload = cached_opener_request(
                "nkuht",
                cache_path.name,
                opener,
                base,
                data=cp950_urlencode(post_fields).encode("ascii"),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": base,
                },
                timeout=180,
                minimum_size=500,
            )
            queries += 1
        rows.extend(nkuht_parse_page(term, department, payload))
        page_numbers = {
            int(value)
            for value in re.findall(rb"GotoPage\((\d+)\)", payload, flags=re.I)
        }
        if page + 1 not in page_numbers:
            break
        page += 1
        if page > 100:
            raise ValueError(f"NKUHT pagination exceeded safety limit for {term}/{op_class}")
    return rows, queries


def nkuht_term_rows(term: str) -> tuple[list[dict], int]:
    class_url = official_url(
        "nkuht",
        "https://classic.nkuht.edu.tw/Pub/GetOpClass.asp?"
        + urllib.parse.urlencode({"Years": term[:3], "Term": term[3]}),
    )
    jar = http.cookiejar.CookieJar()
    opener = twca_verified_opener(jar)
    class_payload = cached_opener_request(
        "nkuht",
        f"nkuht-{term}-classes.html",
        opener,
        class_url,
        timeout=180,
        minimum_size=500,
    )
    classes = nkuht_class_selector_items(term, class_payload)
    if not classes:
        raise ValueError(f"NKUHT class selector is empty for {term}")
    rows = []
    queries = 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(nkuht_class_pages, term, class_name, department, team_no, op_class)
            for class_name, department, team_no, op_class in classes
        ]
        for future in futures:
            class_rows, class_queries = future.result()
            rows.extend(class_rows)
            queries += class_queries
    if not rows:
        raise ValueError(f"NKUHT returned no usable rows for {term}")
    return rows, queries


def import_nkuht() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, queries = nkuht_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    retained = list(current_rows)
    available = [f"{current_term[:3]}-{current_term[3]}"]
    missing = []
    errors = []
    rejected = 0
    for term in reversed(TERMS[:-1]):
        try:
            term_rows, term_queries = nkuht_term_rows(term)
            queries += term_queries
            available.append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            missing.append(f"{term[:3]}-{term[3]}")
            errors.append(f"{term}: {type(error).__name__}")
            continue
        for row in term_rows:
            teachers = [name for name in row["teacherNames"] if name in current_teachers]
            rejected += len(row["teacherNames"]) - len(teachers)
            if not teachers:
                continue
            row["teacherNames"] = teachers
            retained.append(row)
    report = {
        "universityId": "nkuht",
        "status": "imported" if not missing else "partial",
        "officialIndex": SCHOOLS["nkuht"]["index"],
        "availableTerms": sorted(available),
        "missingTerms": sorted(missing),
        "officialQueries": queries,
        "parsedOfferings": len(retained),
        "rejectedWithoutCurrentFaculty": rejected,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
        "note": "校方伺服器漏送 TWCA intermediate；匯入器補入官方 CA intermediate 並維持完整 TLS 驗證",
    }
    if errors:
        report["fetchErrors"] = errors
    return retained, report


def nptu_term_rows(term: str) -> tuple[list[dict], int]:
    files = ensure_webforms_cache("nptu", term)
    rows = []
    for cells in parse_direct_table(files[0].read_bytes(), "A0425S3_dgData"):
        if len(cells) != 17 or cells[0]["text"] == "學年":
            continue
        year = normalize_space(cells[0]["text"])
        semester = normalize_space(cells[1]["text"])
        department = normalize_space(cells[2]["text"])
        subject_code = normalize_space(cells[4]["text"])
        course_anchors = [
            anchor for anchor in cells[5]["anchors"]
            if "btnSUBJ_CNAME" in str(anchor.get("href") or "")
        ]
        name = normalize_space(course_anchors[0]["text"] if course_anchors else cells[5]["text"].split("、", 1)[0])
        teachers = split_instructors(cells[9]["text"])
        if f"{year}{semester}" != term or not department or not subject_code or not name or not teachers:
            continue
        if is_excluded_course(name):
            continue
        rows.append({
            "universityId": "nptu",
            "term": f"{year}-{semester}",
            "courseCode": f"{department}:{subject_code}",
            "name": name,
            "department": department,
            "officialSourceUrl": SCHOOLS["nptu"]["index"],
            "departmentSourceUrl": "https://www.nptu.edu.tw/",
            "teacherNames": teachers,
        })
    if not rows:
        raise ValueError(f"NPTU returned no usable rows for {term}")
    return rows, 7


def import_nptu() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, queries = nptu_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    retained = list(current_rows)
    available = [f"{current_term[:3]}-{current_term[3]}"]
    missing = []
    errors = []
    rejected = 0
    for term in reversed(TERMS[:-1]):
        try:
            term_rows, term_queries = nptu_term_rows(term)
            queries += term_queries
            available.append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            missing.append(f"{term[:3]}-{term[3]}")
            errors.append(f"{term}: {type(error).__name__}")
            continue
        for row in term_rows:
            teachers = [name for name in row["teacherNames"] if name in current_teachers]
            rejected += len(row["teacherNames"]) - len(teachers)
            if not teachers:
                continue
            row["teacherNames"] = teachers
            retained.append(row)
    report = {
        "universityId": "nptu",
        "status": "imported" if not missing else "partial",
        "officialIndex": SCHOOLS["nptu"]["index"],
        "availableTerms": sorted(available),
        "missingTerms": sorted(missing),
        "officialQueries": queries,
        "parsedOfferings": len(retained),
        "rejectedWithoutCurrentFaculty": rejected,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
        "note": "校方公開訪客流程使用動態 session/token；每次匯入皆從官方入口重新建立唯讀訪客工作階段",
    }
    if errors:
        report["fetchErrors"] = errors
    return retained, report


def import_ntua() -> tuple[list[dict], dict]:
    return [], {
        "universityId": "ntua",
        "status": "restricted",
        "officialIndex": SCHOOLS["ntua"]["index"],
        "availableTerms": [],
        "missingTerms": [f"{term[:3]}-{term[3]}" for term in TERMS],
        "officialQueries": 1,
        "parsedOfferings": 0,
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [],
        "note": "校方全校課表須使用帳密登入；目前沒有免登入公開課程端點，未使用刊載的 guest 帳密猜測內部流程。",
    }


NTTU_QUERY = "https://infosys.nttu.edu.tw/n_CourseBase_Select/CourseListPublic.aspx"


def nttu_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, "GridView1")
    year, semester = term[:3], term[3]
    rows = []
    for cells in parser.rows:
        if len(cells) < 19:
            continue
        code = normalize_space(cells[3]["text"])
        name = normalize_space(cells[4]["text"])
        department = normalize_space(cells[1]["text"])
        teachers = split_instructors(cells[11]["text"])
        if not code or not name or not teachers or code == "課程代碼" or is_excluded_course(name):
            continue
        details = ""
        for link in cells[5]["links"]:
            match = re.search(r"CourseInfo1\.aspx\?[^'\"\)\s]+", html.unescape(str(link)), flags=re.I)
            if match:
                details = urljoin(NTTU_QUERY, match.group(0))
                break
        source = official_url("nttu", details) if details else NTTU_QUERY
        rows.append({
            "universityId": "nttu",
            "term": f"{year}-{semester}",
            "courseCode": code,
            "name": name,
            "department": department or "共同課程",
            "officialSourceUrl": source,
            "departmentSourceUrl": NTTU_QUERY,
            "teacherNames": teachers,
        })
    return rows


def nttu_has_next(payload: bytes, current_page: int) -> bool:
    page_numbers = {
        int(value)
        for value in re.findall(rb"Page\$(\d+)", payload, flags=re.I)
    }
    return current_page + 1 in page_numbers


def nttu_cached_term_division(term: str, division: str) -> list[dict] | None:
    rows = []
    page = 1
    while True:
        path = CACHE / f"nttu-{term}-{division}-{page:04d}.html"
        if not cache_entry_is_reusable(path, path.name, 1_000):
            return None
        payload = path.read_bytes()
        rows.extend(nttu_parse_rows(term, payload))
        if not nttu_has_next(payload, page):
            return rows
        page += 1


def nttu_term_division_rows(term: str, division: str) -> tuple[list[dict], int]:
    cached = nttu_cached_term_division(term, division)
    if cached is not None:
        return cached, 1

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        "Referer": NTTU_QUERY,
    }
    landing = opener_read(opener, urllib.request.Request(official_url("nttu", NTTU_QUERY), headers=headers))
    parser = parse_form_and_table(landing)
    query_fields = {
        "DropDownList1": term,
        "DropDownList6": division,
        "DropDownList2": "%",
        "DropDownList3": "%",
        "DropDownList4": "%",
        "TextBox9": "",
        "DropDownList5": "%",
        "DropDownList7": "%",
        "TextBox1": "",
        "DropDownList8": "%",
        "TextBox6": "0",
        "TextBox7": "15",
    }
    fields = dict(parser.hidden)
    fields.update(query_fields)
    fields["Button3"] = "查詢"
    payload = opener_read(opener, urllib.request.Request(
        official_url("nttu", NTTU_QUERY),
        data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = []
    page = 1
    queries = 2
    while True:
        parsed_rows = nttu_parse_rows(term, payload)
        if page == 1 and not parsed_rows:
            # Some division/term combinations legitimately have no offerings.
            if "GridView1" not in payload.decode("utf-8", "replace"):
                raise ValueError(f"NTTU official response has no result grid for {term}/{division}")
        rows.extend(parsed_rows)
        CACHE.mkdir(exist_ok=True)
        (CACHE / f"nttu-{term}-{division}-{page:04d}.html").write_bytes(payload)
        if not nttu_has_next(payload, page):
            break
        parser = parse_form_and_table(payload)
        fields = dict(parser.hidden)
        fields.update(query_fields)
        fields.update({"__EVENTTARGET": "GridView1", "__EVENTARGUMENT": f"Page${page + 1}"})
        fields.pop("Button3", None)
        payload = opener_read(opener, urllib.request.Request(
            official_url("nttu", NTTU_QUERY),
            data=urllib.parse.urlencode(fields).encode(),
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        ))
        page += 1
        queries += 1
        if page > 2_000:
            raise ValueError(f"NTTU pagination exceeded safety limit for {term}/{division}")
    return rows, queries


def nttu_term_rows(term: str) -> tuple[list[dict], int]:
    rows = []
    queries = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(nttu_term_division_rows, term, division) for division in ("1", "2", "3")]
        for future in futures:
            division_rows, division_queries = future.result()
            rows.extend(division_rows)
            queries += division_queries
    return rows, queries


def import_nttu() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = nttu_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTTU current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "nttu",
        "status": "imported",
        "officialIndex": SCHOOLS["nttu"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    # Terms are independent sessions. Eight workers keep the legacy 15-row
    # pager practical without concentrating requests inside a single session.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(nttu_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NTUE_QUERY = "https://nsa.ntue.edu.tw/b09/b09120"
NTUE_DEPARTMENT_DIRECTORY = "https://www.ntue.edu.tw/p/412-1000-2374.php?Lang=zh-tw"


def json_object_after_marker(text: str, marker: str) -> dict:
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"JSON marker is unavailable: {marker}")
    start = text.find("{", start + len(marker))
    if start < 0:
        raise ValueError(f"JSON object is unavailable after marker: {marker}")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(text[start:index + 1])
                if not isinstance(value, dict):
                    raise ValueError("NTUE DataTables payload is not an object")
                return value
    raise ValueError("unterminated JSON object in official NTUE response")


def ntue_parse_rows(term: str, payload: bytes) -> list[dict]:
    page = payload.decode("utf-8", "replace")
    response = json_object_after_marker(page, "setDataTables('tb'")
    raw_rows = response.get("data")
    if not isinstance(raw_rows, list):
        raise ValueError(f"NTUE official response has no DataTables rows for {term}")
    rows = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        name = strip_html(str(raw.get("SemesterCourseName") or ""))
        teachers = split_instructors(raw.get("Teacher"))
        semester_code = normalize_space(raw.get("SemesterCourseNo"))
        department = normalize_space(
            raw.get("StudyCourseCategoryNames")
            or raw.get("StudyClassName")
            or raw.get("CourseClassName")
            or raw.get("DayfgClassTypeName")
        )
        if not name or not teachers or not semester_code or is_excluded_course(name):
            continue
        stable_code = f"{department}:{name}" if department else name
        rows.append({
            "universityId": "ntue",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": stable_code,
            "name": name,
            "department": department or "共同課程",
            "officialSourceUrl": "https://nsa.ntue.edu.tw/guest?school=ntue",
            "departmentSourceUrl": NTUE_DEPARTMENT_DIRECTORY,
            "teacherNames": teachers,
        })
    return rows


def ntue_term_rows(term: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ntue-{term}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 5_001):
        payload = cache_path.read_bytes()
        return ntue_parse_rows(term, payload), 1

    jar = http.cookiejar.CookieJar()
    opener = twca_verified_opener(jar)
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    }
    opener_read(opener, urllib.request.Request(official_url("ntue", "https://nsa.ntue.edu.tw/"), headers=headers))
    opener_read(opener, urllib.request.Request(
        official_url("ntue", "https://nsa.ntue.edu.tw/guest?school=ntue"),
        headers=headers,
    ))
    landing = opener_read(opener, urllib.request.Request(official_url("ntue", NTUE_QUERY), headers=headers))
    token = parse_form_and_table(landing).hidden.get("_token")
    if not token:
        raise ValueError("NTUE form token is unavailable")
    fields = {
        "_token": token,
        "srh[ACADYear][]": term[:3],
        "srh[Semester][]": term[3],
        "event": "search",
    }
    payload = opener_read(opener, urllib.request.Request(
        official_url("ntue", NTUE_QUERY),
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            **headers,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://nsa.ntue.edu.tw",
            "Referer": NTUE_QUERY,
        },
    ))
    rows = ntue_parse_rows(term, payload)
    if not rows:
        raise ValueError(f"NTUE official response has no courses for {term}")
    CACHE.mkdir(exist_ok=True)
    cache_path.write_bytes(payload)
    return rows, 4


def import_ntue() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntue_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTUE current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntue",
        "status": "imported",
        "officialIndex": SCHOOLS["ntue"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
        "note": "校方伺服器漏送 TWCA intermediate；匯入器補入官方 CA intermediate 並維持完整 TLS 驗證",
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(ntue_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


def normalize_academic_unit(value: object) -> str:
    text = normalize_space(value)
    text = re.sub(r"[一二三四五六][甲乙丙丁戊己庚辛A-H]班?$", "", text, flags=re.I)
    text = re.sub(r"(?:一|二|三|四|五|六)年(?:級)?(?:[甲乙丙丁戊己庚辛A-H]班?)?$", "", text, flags=re.I)
    if not re.search(r"[\u3400-\u9fff]", text):
        return "共同課程"
    return text or "共同課程"


def ntcu_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, "dsCurList")
    rows = []
    for cells in parser.rows:
        if len(cells) < 17:
            continue
        department = normalize_academic_unit(cells[0]["text"])
        code = normalize_space(cells[2]["text"])
        name = normalize_space(cells[3]["text"])
        teachers = nutc_teacher_names(cells[9]["text"])
        if not code or not name or not teachers or "科目代碼" in code or is_excluded_course(name):
            continue
        rows.append({
            "universityId": "ntcu",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": code,
            "name": name,
            "department": department,
            "officialSourceUrl": SCHOOLS["ntcu"]["index"],
            "departmentSourceUrl": "https://www.ntcu.edu.tw/Tag?ID=3066",
            "teacherNames": teachers,
        })
    return rows


def ntcu_term_rows(term: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ntcu-{term}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 100_001):
        payload = cache_path.read_bytes()
        return ntcu_parse_rows(term, payload), 1
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    query = official_url("ntcu", SCHOOLS["ntcu"]["index"])
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        "Referer": query,
    }
    landing = opener_read(opener, urllib.request.Request(query, headers=headers))
    parser = parse_form_and_table(landing)
    fields = dict(parser.hidden)
    fields.update({
        "Years": "", "Term": "", "OpClass": "", "Serial": "", "Cos_Short": "",
        "Desire": "", "COSID": "", "DataKey": "",
        "txtYears": term[:3], "txtTerm": term[3], "ddlEdu": "",
        "CosNamekeyWord": "", "btnSearch": "查詢",
    })
    fields.pop("ddlDept", None)
    fields.pop("ddlClass", None)
    payload = opener_read(opener, urllib.request.Request(
        query,
        data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = ntcu_parse_rows(term, payload)
    if not rows:
        raise ValueError(f"NTCU official response has no courses for {term}")
    CACHE.mkdir(exist_ok=True)
    cache_path.write_bytes(payload)
    return rows, 2


def import_ntcu() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntcu_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTCU current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntcu", "status": "imported", "officialIndex": SCHOOLS["ntcu"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"], "missingTerms": [], "officialQueries": current_queries,
        "parsedOfferings": len(current_rows), "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(ntcu_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


def ntub_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, "dsCurList")
    rows = []
    for cells in parser.rows:
        if len(cells) < 10:
            continue
        department = normalize_academic_unit(cells[0]["text"])
        code = normalize_space(cells[2]["text"])
        name = normalize_space(cells[3]["text"])
        teachers = nutc_teacher_names(cells[4]["text"])
        if not code or not name or not teachers or "開課代碼" in code or is_excluded_course(name):
            continue
        rows.append({
            "universityId": "ntub",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": code,
            "name": name,
            "department": department,
            "officialSourceUrl": SCHOOLS["ntub"]["index"],
            "departmentSourceUrl": "https://www.ntub.edu.tw/p/412-1000-6556.php?Lang=zh-tw",
            "teacherNames": teachers,
        })
    return rows


def ntub_term_rows(term: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ntub-{term}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 100_001):
        return ntub_parse_rows(term, cache_path.read_bytes()), 1
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    query = official_url("ntub", SCHOOLS["ntub"]["index"])
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5", "Referer": query,
    }
    landing = opener_read(opener, urllib.request.Request(query, headers=headers))
    parser = parse_form_and_table(landing)
    fields = dict(parser.hidden)
    fields.update({
        "txtYears": term[:3], "txtTerm": term[3], "ddlEdu": "-1",
        "CosNamekeyWord": "", "btnSearch": "查詢",
    })
    fields.pop("ddlDept", None)
    fields.pop("ddlClass", None)
    payload = opener_read(opener, urllib.request.Request(
        query, data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = ntub_parse_rows(term, payload)
    if not rows:
        raise ValueError(f"NTUB official response has no courses for {term}")
    CACHE.mkdir(exist_ok=True)
    cache_path.write_bytes(payload)
    return rows, 2


def import_ntub() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntub_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTUB current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntub", "status": "imported", "officialIndex": SCHOOLS["ntub"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"], "missingTerms": [], "officialQueries": current_queries,
        "parsedOfferings": len(current_rows), "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(ntub_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NTUNHS_QUERY = "https://system10.ntunhs.edu.tw/AcadInfoSystem/Modules/QueryCourse/QueryCourse.aspx"


def ntunhs_teacher_names(value: object) -> list[str]:
    prefix = re.split(r"\d", normalize_space(value), maxsplit=1)[0]
    names = []
    for name in re.findall(r"[\u3400-\u9fff]{2,8}", prefix):
        normalized = normalize_name(name)
        if normalized and normalized not in names:
            names.append(normalized)
    return names


def ntunhs_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, "ContentPlaceHolder1_NewGridView")
    rows = []
    for cells in parser.rows:
        if len(cells) < 15:
            continue
        department = normalize_space(cells[2]["text"])
        code = normalize_space(cells[5]["text"])
        name = normalize_space(cells[6]["text"])
        teachers = ntunhs_teacher_names(cells[7]["text"])
        if not code or not name or not teachers or "科目代號" in code or is_excluded_course(name):
            continue
        rows.append({
            "universityId": "ntunhs", "term": f"{term[:3]}-{term[3]}",
            "courseCode": f"{department}:{code}", "name": name,
            "department": department or "共同課程", "officialSourceUrl": NTUNHS_QUERY,
            "departmentSourceUrl": "https://www.ntunhs.edu.tw/p/412-1000-84.php?Lang=zh-tw",
            "teacherNames": teachers,
        })
    return rows


def ntunhs_term_rows(term: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ntunhs-{term}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 100_001):
        return ntunhs_parse_rows(term, cache_path.read_bytes()), 1
    opener = urllib.request.build_opener()
    query = official_url("ntunhs", NTUNHS_QUERY)
    headers = {"User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)", "Referer": query}
    landing = opener_read(opener, urllib.request.Request(query, headers=headers))
    parser = parse_form_and_table(landing)
    checkbox = next((
        value.get("name") for value in parser.inputs
        if value.get("value") == term and "cblsemno" in value.get("name", "").lower()
    ), None)
    if not checkbox:
        raise ValueError(f"NTUNHS semester checkbox is unavailable for {term}")
    prefix = "ctl00$ContentPlaceHolder1$"
    fields = dict(parser.hidden)
    fields.update({
        prefix + "hidSystemType": "N", prefix + "ddlSem": term, checkbox: term,
        prefix + "ddlDept": "", prefix + "ddlProgram": "", prefix + "ddlDeptProgram": "",
        prefix + "ddlNewDept": "", prefix + "ddlNewDept_dummy": "", prefix + "ddlCompare": "",
        prefix + "ddlNewCompare": "", prefix + "txtTeachNo": "", prefix + "txtTeachName": "",
        prefix + "txtCourseNo": "", prefix + "txtCourseName": "", prefix + "txtClassNo": "",
        prefix + "txtClassName": "", prefix + "txtRoomNo": "", prefix + "txtCNT": "",
        prefix + "btnQuery": "查詢",
    })
    payload = opener_read(opener, urllib.request.Request(
        query, data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = ntunhs_parse_rows(term, payload)
    if not rows:
        raise ValueError(f"NTUNHS official response has no courses for {term}")
    CACHE.mkdir(exist_ok=True)
    cache_path.write_bytes(payload)
    return rows, 2


def import_ntunhs() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ntunhs_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NTUNHS current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ntunhs", "status": "imported", "officialIndex": SCHOOLS["ntunhs"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"], "missingTerms": [], "officialQueries": current_queries,
        "parsedOfferings": len(current_rows), "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(ntunhs_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NCUE_QUERY = "https://webapt.ncue.edu.tw/DEANV2/Other/OB010"


def ncue_term_branch_rows(term: str, branch: str) -> tuple[list[dict], int]:
    cache_path = CACHE / f"ncue-{term}-{branch}.html"
    if cache_entry_is_reusable(cache_path, cache_path.name, 1_001):
        payload = cache_path.read_bytes()
    else:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        headers = {
            "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        }
        landing = opener_read(opener, urllib.request.Request(
            official_url("ncue", SCHOOLS["ncue"]["index"]),
            headers=headers,
        ))
        token = parse_form_and_table(landing).hidden.get("__RequestVerificationToken")
        if not token:
            raise ValueError("NCUE anti-forgery token is unavailable")
        fields = {
            "__RequestVerificationToken": token,
            "sel_cls_branch": branch,
            "sel_scr_english": "",
            "sel_SCR_IS_DIS_LEARN": "",
            "sel_yms_year": term[:3],
            "sel_yms_smester": term[3],
            "scr_selcode": "",
            "sel_cls_id": "",
            "sel_sct_week": "",
            "sub_name": "",
            "emp_name": "",
            "CatchBot": "",
        }
        payload = opener_read(opener, urllib.request.Request(
            official_url("ncue", NCUE_QUERY),
            data=urllib.parse.urlencode(fields).encode(),
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://webapt.ncue.edu.tw",
                "Referer": SCHOOLS["ncue"]["index"],
                "X-Requested-With": "XMLHttpRequest",
            },
        ))
        CACHE.mkdir(exist_ok=True)
        cache_path.write_bytes(payload)

    rows = []
    for cells in parse_all_html_rows(payload):
        if len(cells) < 17:
            continue
        code = normalize_space(cells[1]["text"])
        department = normalize_space(cells[2]["text"])
        name = normalize_space(cells[3]["text"])
        teachers = split_instructors(cells[9]["text"])
        if not code or not name or not teachers or "課程代碼" in code or is_excluded_course(name):
            continue
        rows.append({
            "universityId": "ncue",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": code,
            "name": name,
            "department": department or ("日間部" if branch == "D" else "進修學院"),
            "officialSourceUrl": SCHOOLS["ncue"]["index"],
            "departmentSourceUrl": SCHOOLS["ncue"]["index"],
            "teacherNames": teachers,
        })
    return rows, 2


def ncue_term_rows(term: str) -> tuple[list[dict], int]:
    rows = []
    queries = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ncue_term_branch_rows, term, branch) for branch in ("D", "N")]
        for future in futures:
            branch_rows, branch_queries = future.result()
            rows.extend(branch_rows)
            queries += branch_queries
    return rows, queries


def import_ncue() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ncue_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NCUE current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ncue",
        "status": "imported",
        "officialIndex": SCHOOLS["ncue"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(ncue_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NCYU_DEPARTMENT_FORM = "https://web085003.adm.ncyu.edu.tw/pub_depta1.aspx"
NCYU_QUERY = "https://web085003.adm.ncyu.edu.tw/pub_depta2.aspx"


def ncyu_department_map() -> dict[str, str]:
    payload = cached_request(
        "ncyu",
        "ncyu-departments.html",
        NCYU_DEPARTMENT_FORM,
        minimum_size=10_000,
    )
    page = payload.decode("cp950", "replace")
    select = re.search(r'<select[^>]+name=["\']WebDep67["\'][^>]*>(.*?)</select>', page, flags=re.I | re.S)
    if not select:
        raise ValueError("NCYU department selector is unavailable")
    departments = {}
    for value, label in re.findall(
        r'<option[^>]+value=["\']([^"\']+)["\'][^>]*>(.*?)</option>',
        select.group(1),
        flags=re.I | re.S,
    ):
        value = normalize_space(value)
        label = strip_html(label)
        if value and label and "請選擇" not in label:
            departments[value] = label
    if not departments:
        raise ValueError("NCYU department map is empty")
    return departments


def ncyu_term_rows(term: str, departments: dict[str, str]) -> tuple[list[dict], int]:
    def fetch_department(item: tuple[str, str]) -> tuple[str, str, bytes]:
        code, department = item
        payload = cached_request(
            "ncyu",
            f"ncyu-{term}-{code}.html",
            NCYU_QUERY,
            data=urllib.parse.urlencode({
                "WebPid1": "",
                "Language": "zh-TW",
                "WebYear1": term[:3],
                "WebTerm1": term[3],
                "WebDep67": code,
            }).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://web085003.adm.ncyu.edu.tw",
                "Referer": NCYU_DEPARTMENT_FORM,
            },
            minimum_size=100,
        )
        return code, department, payload

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for department_code, department_name, payload in executor.map(fetch_department, sorted(departments.items())):
            for cells in parse_all_html_rows(payload, "cp950"):
                if len(cells) < 27:
                    continue
                opening_code = normalize_space(cells[2]["text"])
                sequence = normalize_space(cells[3]["text"])
                name = normalize_space(cells[4]["text"])
                permanent_code = normalize_space(cells[5]["text"])
                department = normalize_space(cells[6]["text"]) or department_name
                teachers = split_instructors(cells[19]["text"])
                if not name or not teachers or is_excluded_course(name):
                    continue
                course_code = permanent_code or f"{opening_code}:{sequence}"
                if not course_code:
                    continue
                details = ""
                for link in cells[4]["links"]:
                    match = re.search(r"pub_tagoutline\.aspx\?[^'\"\)\s]+", str(link), flags=re.I)
                    if match:
                        details = urljoin(NCYU_QUERY, html.unescape(match.group(0)))
                        break
                source = official_url("ncyu", details) if details else NCYU_DEPARTMENT_FORM
                rows.append({
                    "universityId": "ncyu",
                    "term": f"{term[:3]}-{term[3]}",
                    "courseCode": course_code,
                    "name": name,
                    "department": department,
                    "officialSourceUrl": source,
                    "departmentSourceUrl": NCYU_DEPARTMENT_FORM,
                    "teacherNames": teachers,
                })
    return rows, len(departments)


def import_ncyu() -> tuple[list[dict], dict]:
    departments = ncyu_department_map()
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = ncyu_term_rows(current_term, departments)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NCYU current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "ncyu",
        "status": "imported",
        "officialIndex": SCHOOLS["ncyu"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries + 1,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(ncyu_term_rows, term, departments): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


YUNTECH_QUERY = "https://webapp.yuntech.edu.tw/webnewcas/course/querycour.aspx"
YUNTECH_TABLE_ID = "ctl00_MainContent_Course_GridView"


def yuntech_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, YUNTECH_TABLE_ID)
    rows = []
    for cells in parser.rows:
        if len(cells) < 13:
            continue
        semester_code = normalize_space(cells[0]["text"])
        department_code = normalize_space(cells[1]["text"])
        name = normalize_space(cells[2]["text"])
        department = normalize_space(cells[3]["text"])
        teachers = split_instructors(cells[8]["text"])
        if not name or not teachers or is_excluded_course(name) or "課程名稱" in name:
            continue
        code = department_code or semester_code
        if not code:
            continue
        details = ""
        for link in cells[2]["links"]:
            match = re.search(r"(?:WebNewCAS/)?Course/Plan/Query\.aspx\?[^'\"\)\s]+", html.unescape(str(link)), flags=re.I)
            if match:
                relative = match.group(0)
                if relative.lower().startswith("webnewcas/"):
                    relative = "/" + relative
                details = urljoin(YUNTECH_QUERY, relative)
                break
        source = official_url("yuntech", details) if details else YUNTECH_QUERY
        rows.append({
            "universityId": "yuntech",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": code,
            "name": name,
            "department": department or "共同課程",
            "officialSourceUrl": source,
            "departmentSourceUrl": YUNTECH_QUERY,
            "teacherNames": teachers,
        })
    return rows


def yuntech_has_next(payload: bytes) -> bool:
    return bool(re.search(rb"Page\$(?:Next|\d+)", payload, flags=re.I)) and bool(
        re.search(rb"Page\$Next", payload, flags=re.I)
    )


def yuntech_cached_term(term: str) -> list[dict] | None:
    rows = []
    page = 1
    while True:
        path = CACHE / f"yuntech-{term}-{page:04d}.html"
        if not cache_entry_is_reusable(path, path.name, 1_000):
            return None
        payload = path.read_bytes()
        rows.extend(yuntech_parse_rows(term, payload))
        if not yuntech_has_next(payload):
            return rows
        page += 1


def yuntech_term_rows(term: str) -> tuple[list[dict], int]:
    cached = yuntech_cached_term(term)
    if cached is not None:
        return cached, 1

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        "Referer": YUNTECH_QUERY,
    }
    landing = opener_read(opener, urllib.request.Request(official_url("yuntech", YUNTECH_QUERY), headers=headers))
    parser = parse_form_and_table(landing)
    fields = dict(parser.hidden)
    fields.update({
        "ctl00$MainContent$AcadSeme": term,
        "ctl00$MainContent$College": "",
        "ctl00$MainContent$DeptCode": "",
        "ctl00$MainContent$CurrentSubj": "",
        "ctl00$MainContent$SubjName": "%",
        "ctl00$MainContent$Instructor": "",
        "ctl00$MainContent$TextBoxWatermarkExtender1_ClientState": "",
        "ctl00$MainContent$TextBoxWatermarkExtender2_ClientState": "",
        "ctl00$MainContent$TextBoxWatermarkExtender3_ClientState": "",
        "ctl00$MainContent$Submit": "執行查詢",
    })
    payload = opener_read(opener, urllib.request.Request(
        official_url("yuntech", YUNTECH_QUERY),
        data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = []
    page = 1
    queries = 2
    while True:
        page_rows = yuntech_parse_rows(term, payload)
        if page == 1 and not page_rows:
            raise ValueError(f"YunTech open query returned no verified rows for {term}")
        rows.extend(page_rows)
        CACHE.mkdir(exist_ok=True)
        (CACHE / f"yuntech-{term}-{page:04d}.html").write_bytes(payload)
        if not yuntech_has_next(payload):
            break
        parser = parse_form_and_table(payload)
        fields = dict(parser.hidden)
        fields.update({
            "__EVENTTARGET": "ctl00$MainContent$Course_GridView",
            "__EVENTARGUMENT": "Page$Next",
        })
        payload = opener_read(opener, urllib.request.Request(
            official_url("yuntech", YUNTECH_QUERY),
            data=urllib.parse.urlencode(fields).encode(),
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        ))
        page += 1
        queries += 1
        if page > 2_000:
            raise ValueError(f"YunTech pagination exceeded safety limit for {term}")
    return rows, queries


def import_yuntech() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = yuntech_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("YunTech current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "yuntech",
        "status": "imported",
        "officialIndex": SCHOOLS["yuntech"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
        "note": "官方 WebForms 課程查詢；以校方支援的查詢結果逐頁核對",
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(yuntech_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


UTAIPEI_BASE = "https://shcourse.utaipei.edu.tw/utaipei/ag_pro/"
UTAIPEI_COLLEGES = ("24", "51", "UZ", "WZ", "XS", "XZ", "YZ", "ZY", "ZZ")


def utaipei_unit_map(term: str) -> tuple[dict[str, tuple[str, str]], int]:
    year, semester = term[:3], term[3]

    def fetch_college(college: str) -> dict[str, tuple[str, str]]:
        url = official_url("utaipei", urljoin(UTAIPEI_BASE, "ag304_face.jsp") + "?" + urllib.parse.urlencode({
            "yms_yms": f"{year}#{semester}",
            "dpt_id": college,
            "unt_id": "",
            "ls_year": year,
            "ls_sms": semester,
            "uid": "null",
            "ls_years": "0",
            "ls_smss": "0",
        }))
        payload = cached_request(
            "utaipei",
            f"utaipei-{term}-college-{college}.html",
            url,
            minimum_size=300,
        )
        page = payload.decode("utf-8", "replace")
        select = re.search(r'<select[^>]+name=["\']?unt_id["\']?[^>]*>(.*?)</select>', page, flags=re.I | re.S)
        if not select:
            return {}
        result = {}
        for value, label in re.findall(
            r'<option[^>]+value=["\']?([^"\' >]+)["\']?[^>]*>(.*?)</option>',
            select.group(1),
            flags=re.I | re.S,
        ):
            value = normalize_space(value)
            label = strip_html(label)
            label = normalize_space(re.sub(r"\b\d{2,3}[a-z]\b", "", label.replace("�", ""), flags=re.I))
            if value and label and "請選擇" not in label and "全部" not in label:
                result[value] = (label, college)
        return result

    units = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for result in executor.map(fetch_college, UTAIPEI_COLLEGES):
            units.update(result)
    if not units:
        raise ValueError(f"UTaipei official unit map is empty for {term}")
    return units, len(UTAIPEI_COLLEGES)


def utaipei_class_ids(term: str, college: str, unit: str) -> list[str]:
    year, semester = term[:3], term[3]
    url = official_url("utaipei", urljoin(UTAIPEI_BASE, "ag304_02.jsp") + "?" + urllib.parse.urlencode({
        "yms_yms": f"{year}#{semester}",
        "dpt_id": college,
        "unt_id": unit,
        "ls_year": year,
        "ls_sms": semester,
        "uid": "null",
        "ls_years": "0",
        "ls_smss": "0",
    }))
    payload = cached_request(
        "utaipei",
        f"utaipei-{term}-unit-{unit}.html",
        url,
        minimum_size=100,
    )
    page = payload.decode("utf-8", "replace")
    return list(dict.fromkeys(re.findall(r"go_next\(\s*[\"']([^\"']+)[\"']\s*\)", page, flags=re.I)))


def utaipei_teacher_names(value: object) -> list[str]:
    text = normalize_space(value)
    names = []
    for name in re.findall(r"(?:^|[、,，;/；\s])([\u3400-\u9fff]{2,6})\s*(?=[(（])", text):
        normalized = normalize_name(name)
        if normalized and normalized not in names:
            names.append(normalized)
    if names:
        return names
    prefix = re.split(r"[(（]", text, maxsplit=1)[0]
    return split_instructors(prefix)


def utaipei_class_rows(term: str, class_id: str, department: str) -> list[dict]:
    year, semester = term[:3], term[3]
    url = official_url("utaipei", urljoin(UTAIPEI_BASE, "ag304_03.jsp") + "?" + urllib.parse.urlencode({
        "arg01": year,
        "arg02": semester,
        "arg": class_id,
        "uid": "null",
    }))
    payload = cached_request(
        "utaipei",
        f"utaipei-{term}-class-{class_id}.html",
        url,
        minimum_size=300,
    )
    page = payload.decode("utf-8", "replace")
    rows = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.I | re.S):
        raw_cells = re.findall(r"<td\b([^>]*)>(.*?)</td>", row_html, flags=re.I | re.S)
        if len(raw_cells) != 12:
            continue
        values = [strip_html(content) for _, content in raw_cells]
        selection_code = normalize_space(values[0])
        name = normalize_space(values[1])
        teachers = utaipei_teacher_names(values[8])
        if not selection_code or not name or not teachers or "選課代碼" in selection_code or is_excluded_course(name):
            continue
        onclick = raw_cells[11][0]
        match = re.search(
            r"go_next\(\s*[\"']?(\d+)[\"']?\s*,\s*[\"']?(\d+)[\"']?\s*,\s*[\"']([^\"']+)[\"']\s*\)",
            html.unescape(onclick),
            flags=re.I,
        )
        source = url
        permanent_code = ""
        if match:
            arg04 = match.group(3)
            permanent_code = normalize_space(arg04.rsplit(",", 1)[-1])
            source = official_url("utaipei", urljoin(UTAIPEI_BASE, "ag064_print.jsp") + "?" + urllib.parse.urlencode({
                "uid": "null",
                "arg01": match.group(1),
                "arg02": match.group(2),
                "arg04": arg04,
            }))
        rows.append({
            "universityId": "utaipei",
            "term": f"{year}-{semester}",
            "courseCode": permanent_code or f"{department}:{name}",
            "name": name,
            "department": department,
            "officialSourceUrl": source,
            "departmentSourceUrl": SCHOOLS["utaipei"]["index"],
            "teacherNames": teachers,
            "selectionCode": selection_code,
        })
    return rows


def utaipei_term_rows(term: str) -> tuple[list[dict], int]:
    units, queries = utaipei_unit_map(term)

    def fetch_unit(item: tuple[str, tuple[str, str]]) -> tuple[str, str, list[str]]:
        unit, (department, college) = item
        return unit, department, utaipei_class_ids(term, college, unit)

    classes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for unit, department, class_ids in executor.map(fetch_unit, sorted(units.items())):
            queries += 1
            classes.extend((class_id, department) for class_id in class_ids)

    rows_by_selection: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(utaipei_class_rows, term, class_id, department)
            for class_id, department in classes
        ]
        for future in concurrent.futures.as_completed(futures):
            queries += 1
            for row in future.result():
                key = row.pop("selectionCode")
                existing = rows_by_selection.get(key)
                if existing is None:
                    rows_by_selection[key] = row
                    continue
                existing["teacherNames"] = sorted(set(existing["teacherNames"] + row["teacherNames"]))
                existing_departments = existing["department"].split("/")
                if row["department"] not in existing_departments:
                    existing["department"] += "/" + row["department"]
    return list(rows_by_selection.values()), queries


def import_utaipei() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = utaipei_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("UTaipei current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "utaipei",
        "status": "imported",
        "officialIndex": SCHOOLS["utaipei"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(utaipei_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NUTC_LIST_JS = "https://aisap.nutc.edu.tw/public/clsno_list.js"


def nutc_class_map(term: str, division_code: str) -> dict[str, str]:
    payload = cached_request(
        "nutc",
        "nutc-clsno-list.js",
        NUTC_LIST_JS,
        minimum_size=100_000,
    )
    source = payload.decode("utf-8", "replace")
    key = f"D{division_code}_{term}"
    match = re.search(
        rf"g_Clsno\[['\"]{re.escape(key)}['\"]\]\s*=\s*(\[\[.*?\]\])\s*;",
        source,
        flags=re.S,
    )
    if not match:
        raise ValueError(f"NUTC official class index is unavailable for {key}")
    values = json.loads(match.group(1))
    result = {}
    for value in values:
        if isinstance(value, list) and len(value) >= 2:
            class_id = normalize_space(value[0])
            name = normalize_space(value[1])
            if class_id and name:
                result[class_id] = name
    return result


def nutc_department_name(class_name: str) -> str:
    name = re.sub(r"[一二三四五六][甲乙丙丁戊己庚辛].*$", "", normalize_space(class_name))
    return name or normalize_space(class_name)


def nutc_teacher_names(value: object) -> list[str]:
    text = re.sub(r"\b[A-Za-z0-9_-]{2,}\s+(?=[\u3400-\u9fff])", "", normalize_space(value))
    return split_instructors(text)


def nutc_parse_page(term: str, division: str, class_id: str, payload: bytes, source: str) -> list[dict]:
    rows = []
    for cells in parse_all_html_rows(payload):
        if len(cells) != 13:
            continue
        code = normalize_space(cells[1]["text"])
        class_name = normalize_space(cells[2]["text"])
        name = normalize_space(cells[3]["text"])
        teachers = nutc_teacher_names(cells[9]["text"])
        if not code or not name or not teachers or code == "課程代碼" or is_excluded_course(name):
            continue
        department = nutc_department_name(class_name)
        rows.append({
            "universityId": "nutc",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": f"{department}:{name}",
            "name": name,
            "department": department,
            "officialSourceUrl": source,
            "departmentSourceUrl": SCHOOLS["nutc"]["index"],
            "teacherNames": teachers,
        })
    return rows


def nutc_class_rows(term: str, division: str, class_id: str) -> tuple[list[dict], int]:
    base = f"https://aisap.nutc.edu.tw/public/{division}/course_list.aspx"

    def fetch_page(page: int) -> tuple[bytes, str]:
        query = {"sem": term, "clsno": class_id}
        if page > 1:
            query["_p"] = str(page)
        source = official_url("nutc", base + "?" + urllib.parse.urlencode(query))
        payload = cached_request(
            "nutc",
            f"nutc-{division}-{term}-{class_id}-{page:03d}.html",
            source,
            minimum_size=100,
        )
        return payload, source

    first_payload, first_source = fetch_page(1)
    page = first_payload.decode("utf-8", "replace")
    total_match = re.search(r"共有\s*(?:<[^>]+>\s*)*([0-9,]+)", page, flags=re.I)
    total = int(total_match.group(1).replace(",", "")) if total_match else 0
    page_count = max(1, (total + 19) // 20) if total else 1
    rows = nutc_parse_page(term, division, class_id, first_payload, first_source)
    if page_count > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            for payload, source in executor.map(fetch_page, range(2, page_count + 1)):
                rows.extend(nutc_parse_page(term, division, class_id, payload, source))
    return rows, page_count


def nutc_term_rows(term: str) -> tuple[list[dict], int]:
    tasks = []
    for division_code, division in (("1", "day"), ("2", "nig")):
        classes = nutc_class_map(term, division_code)
        tasks.extend((division, class_id) for class_id in classes)
    rows = []
    queries = 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(nutc_class_rows, term, division, class_id) for division, class_id in tasks]
        for future in concurrent.futures.as_completed(futures):
            class_rows, query_count = future.result()
            rows.extend(class_rows)
            queries += query_count
    return rows, queries


def import_nutc() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = nutc_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NUTC current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "nutc",
        "status": "imported",
        "officialIndex": SCHOOLS["nutc"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(nutc_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


NPUST_QUERY = "https://course.npust.edu.tw/courseengqry/course/CourseQuery.aspx"
NPUST_TABLE_ID = "ctl00_ContentPlaceHolder1_GridView1"


def npust_parse_rows(term: str, payload: bytes) -> list[dict]:
    parser = parse_form_and_table(payload, NPUST_TABLE_ID)
    rows = []
    for cells in parser.rows:
        if len(cells) < 16:
            continue
        department = normalize_space(cells[0]["text"])
        teachers = split_instructors(cells[2]["text"])
        code = normalize_space(cells[3]["text"])
        name = normalize_space(cells[4]["text"])
        if (
            not code or not name or not teachers
            or code in {"Course Code", "Course No"}
            or name == "Course Name"
            or teachers == ["Teacher"]
            or is_excluded_course(name)
        ):
            continue
        rows.append({
            "universityId": "npust",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": f"{department}:{code}",
            "name": name,
            "department": department or "General Courses",
            "officialSourceUrl": NPUST_QUERY,
            "departmentSourceUrl": SCHOOLS["npust"]["index"],
            "teacherNames": teachers,
        })
    return rows


def npust_has_next(payload: bytes, current_page: int) -> bool:
    page_numbers = {int(value) for value in re.findall(rb"Page\$(\d+)", payload, flags=re.I)}
    return current_page + 1 in page_numbers


def npust_cached_term(term: str) -> list[dict] | None:
    rows = []
    page = 1
    while True:
        path = CACHE / f"npust-{term}-{page:04d}.html"
        if not cache_entry_is_reusable(path, path.name, 1_000):
            return None
        payload = path.read_bytes()
        rows.extend(npust_parse_rows(term, payload))
        if not npust_has_next(payload, page):
            return rows
        page += 1


def npust_term_rows(term: str) -> tuple[list[dict], int]:
    cached = npust_cached_term(term)
    if cached is not None:
        return cached, 1

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        "Referer": NPUST_QUERY,
    }
    landing = opener_read(opener, urllib.request.Request(official_url("npust", NPUST_QUERY), headers=headers))
    parser = parse_form_and_table(landing)
    selects = {
        "ctl00$ContentPlaceHolder1$DropDownListAca": term[:3],
        "ctl00$ContentPlaceHolder1$DropDownListTerm": term[3],
    }
    fields = dict(parser.hidden)
    fields.update(selects)
    fields["ctl00$ContentPlaceHolder1$Submit"] = "Search"
    payload = opener_read(opener, urllib.request.Request(
        official_url("npust", NPUST_QUERY),
        data=urllib.parse.urlencode(fields).encode(),
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    ))
    rows = []
    page = 1
    queries = 2
    while True:
        page_rows = npust_parse_rows(term, payload)
        if page == 1 and not page_rows:
            raise ValueError(f"NPUST official response has no courses for {term}")
        rows.extend(page_rows)
        CACHE.mkdir(exist_ok=True)
        (CACHE / f"npust-{term}-{page:04d}.html").write_bytes(payload)
        if not npust_has_next(payload, page):
            break
        parser = parse_form_and_table(payload)
        fields = dict(parser.hidden)
        fields.update(selects)
        fields.update({
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$GridView1",
            "__EVENTARGUMENT": f"Page${page + 1}",
        })
        payload = opener_read(opener, urllib.request.Request(
            official_url("npust", NPUST_QUERY),
            data=urllib.parse.urlencode(fields).encode(),
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        ))
        page += 1
        queries += 1
        if page > 500:
            raise ValueError(f"NPUST pagination exceeded safety limit for {term}")
    return rows, queries


def import_npust() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = npust_term_rows(current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NPUST current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "npust",
        "status": "imported",
        "officialIndex": SCHOOLS["npust"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
        "note": "校方公開結構化課表；相同流水號的多時段列合併為一門課",
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(npust_term_rows, term): term for term in history_terms}
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


def nfu_department_map(path: str) -> dict[str, str]:
    page = cached_request(
        "nfu",
        f"nfu-{path.replace('/', '-') or 'current'}-index.html",
        f"https://tqas.nfu.edu.tw/course_schedule{path}",
        minimum_size=5_000,
    ).decode("utf-8", "replace")
    select = re.search(
        r'<select[^>]+name=["\']dept_code_no["\'][^>]*>(.*?)</select>',
        page,
        flags=re.I | re.S,
    )
    if not select:
        raise ValueError(f"NFU department selector is unavailable for {path or 'current'}")
    result = {}
    for code, label in re.findall(
        r'<option[^>]+value=["\']([^"\']+)["\'][^>]*>(.*?)</option>',
        select.group(1),
        flags=re.I | re.S,
    ):
        code = normalize_space(code)
        label = strip_html(label)
        if code and code != "-1" and label and not label.endswith("學院"):
            result[code] = label
    return result


def nfu_term_rows(term: str, department_maps: dict[str, dict[str, str]]) -> tuple[list[dict], int]:
    year, semester = term[:3], term[3]
    path = "" if int(year) >= 113 else "/old"
    endpoint = official_url("nfu", f"https://tqas.nfu.edu.tw/course_schedule{path}")
    departments = department_maps[path]

    def fetch_department(item: tuple[str, str]) -> tuple[str, str, str, list[dict]]:
        department_code, department_name = item
        query = {
            "course_year": year,
            "course_seme": semester,
            "clss_colo_no": "-1",
            "dept_code_no": department_code,
            "divi_no": "-1",
            "course_cname": "",
            "teacher_name": "",
            "course_seq_code": "",
            "draw": "1",
            "start": "0",
            "length": "10000",
        }
        source = official_url("nfu", endpoint + "?" + urllib.parse.urlencode(query))
        payload = cached_request(
            "nfu",
            f"nfu-{term}-{department_code}.json",
            source,
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": endpoint,
            },
            minimum_size=20,
        )
        response = json.loads(payload.decode("utf-8-sig"))
        raw_rows = response.get("data") if isinstance(response, dict) else None
        if not isinstance(raw_rows, list):
            raise ValueError(f"NFU response has no data for {term}/{department_code}")
        expected = int(response.get("recordsFiltered") or len(raw_rows))
        if expected != len(raw_rows):
            raise ValueError(
                f"NFU incomplete response for {term}/{department_code}: {len(raw_rows)}/{expected}"
            )
        return department_code, department_name, source, raw_rows

    rows_by_offering: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # The unfiltered official response also contains common/administrative
        # offerings which are not represented by a department option.
        results = executor.map(fetch_department, sorted(departments.items()) + [("-1", "共同課程")])
        for department_code, department, query_source, raw_rows in results:
            for raw in raw_rows:
                name = normalize_space(raw.get("course_cname") or raw.get("course_ename"))
                teachers = split_instructors(raw.get("teacher_name"))
                offering_id = normalize_space(raw.get("course_id") or raw.get("DT_RowId"))
                if not name or not teachers or not offering_id or is_excluded_course(name):
                    continue
                if department_code == "-1" and offering_id in rows_by_offering:
                    continue
                link_match = re.search(
                    r"href=['\"]([^'\"]+/detail/[^'\"]+)",
                    str(raw.get("action") or ""),
                    flags=re.I,
                )
                source = official_url("nfu", html.unescape(link_match.group(1))) if link_match else query_source
                rows_by_offering[offering_id] = {
                    "universityId": "nfu",
                    "term": f"{year}-{semester}",
                    "courseCode": f"{department_code}:{name}",
                    "name": name,
                    "department": department,
                    "officialSourceUrl": source,
                    "departmentSourceUrl": query_source,
                    "teacherNames": teachers,
                }
    return list(rows_by_offering.values()), len(departments) + 1


def import_nfu() -> tuple[list[dict], dict]:
    department_maps = {
        "": nfu_department_map(""),
        "/old": nfu_department_map("/old"),
    }
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = nfu_term_rows(current_term, department_maps)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NFU current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "nfu",
        "status": "imported",
        "officialIndex": SCHOOLS["nfu"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries + 2,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(nfu_term_rows, term, department_maps): term
            for term in history_terms
        }
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    return rows, report


def nutn_session() -> tuple[urllib.request.OpenerDirector, str, str]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    index = official_url("nutn", SCHOOLS["nutn"]["index"])
    with opener.open(urllib.request.Request(index, headers={
        "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
    }), timeout=60) as response:
        page = response.read().decode("utf-8", "replace")
    match = re.search(r'id=["\']ctl00_hv_token["\'][^>]+value=["\']([^"\']+)', page, flags=re.I)
    if not match:
        raise ValueError("NUTN public CSRF token is unavailable")
    return opener, match.group(1), page


def nutn_json_post(
    opener: urllib.request.OpenerDirector,
    token: str,
    filename: str,
    path: str,
    body: dict[str, str],
) -> list[dict]:
    url = official_url("nutn", "https://academics.nutn.edu.tw" + path)
    CACHE.mkdir(exist_ok=True)
    cache_path = CACHE / filename
    if cache_entry_is_reusable(cache_path, filename, 2):
        payload = cache_path.read_bytes()
    else:
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "User-Agent": "WZUNAA-official-course-audit/1.0 (+https://map.scmwcscr.com)",
                "Content-Type": "application/json; charset=utf-8",
                "X-CSRF-Token": token,
                "Referer": SCHOOLS["nutn"]["index"],
            },
        )
        with opener.open(request, timeout=120) as response:
            payload = response.read()
        cache_path.write_bytes(payload)
    result = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(result, list):
        raise ValueError(f"NUTN response is not a list: {path}")
    return [row for row in result if isinstance(row, dict)]


def nutn_catalog() -> tuple[list[tuple[str, str, str, str]], int]:
    opener, token, page = nutn_session()
    colleges = nutn_json_post(opener, token, "nutn-colleges.json", "/Course/api/Query/GetCollege", {"l": "zh-TW"})
    categories: dict[tuple[str, str, str], str] = {}
    query_count = 1
    for kind in ("2", "3"):
        for college in colleges:
            college_code = normalize_space(college.get("code"))
            if not college_code:
                continue
            departments = nutn_json_post(
                opener,
                token,
                f"nutn-kind-{kind}-college-{college_code}.json",
                "/Course/api/Query/GetDept",
                {"t": kind, "f": college_code, "l": "zh-TW"},
            )
            query_count += 1
            for department in departments:
                code = normalize_space(department.get("code"))
                label = normalize_space(department.get("code_name"))
                if code and label:
                    categories[(kind, "dc", code)] = label
    for kind, path, filter_key, filename in (
        ("4", "/Course/api/Query/GetGeArea", "ge", "nutn-general-areas.json"),
        ("5", "/Course/api/Query/GetTaClass", "ta", "nutn-teacher-programs.json"),
    ):
        options = nutn_json_post(opener, token, filename, path, {"l": "zh-TW"})
        query_count += 1
        for option in options:
            code = normalize_space(option.get("code"))
            label = normalize_space(option.get("code_name"))
            if code and label:
                categories[(kind, filter_key, code)] = label
    other_select = re.search(r'<select[^>]+id=["\']lstOther["\'][^>]*>(.*?)</select>', page, flags=re.I | re.S)
    if other_select:
        for code, label in re.findall(
            r'<option[^>]+value=["\']([^"\']+)["\'][^>]*>(.*?)</option>',
            other_select.group(1),
            flags=re.I | re.S,
        ):
            code, label = normalize_space(code), strip_html(label)
            if code and label:
                categories[("6", "ot", code)] = label
    return [(kind, key, code, label) for (kind, key, code), label in sorted(categories.items())], query_count


def nutn_term_rows(
    term: str,
    categories: list[tuple[str, str, str, str]],
) -> tuple[list[dict], int]:
    opener, token, _ = nutn_session()

    def fetch_category(item: tuple[str, str, str, str]) -> tuple[tuple[str, str, str, str], list[dict]]:
        kind, filter_key, code, label = item
        filters = {"dc": "", "ge": "", "ta": "", "ot": ""}
        filters[filter_key] = code
        body = {
            "acs": term,
            "kw": "",
            **filters,
            "gr": "",
            "ch": "",
            "we": "",
            "ki": kind,
            "ll": "zh-TW",
        }
        rows = nutn_json_post(
            opener,
            token,
            f"nutn-{term}-{kind}-{filter_key}-{code}.json",
            "/Course/api/Query/GetCourse",
            body,
        )
        return item, rows

    offerings: dict[tuple[str, str, str], dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for (kind, _filter_key, category_code, category_label), raw_rows in executor.map(fetch_category, categories):
            for raw in raw_rows:
                if normalize_space(raw.get("Result")) not in {"", "00"}:
                    continue
                name = normalize_space(raw.get("CourName") or raw.get("CourEngName"))
                teachers = split_instructors(raw.get("TeaName") or raw.get("TeaName1"))
                code = normalize_space(raw.get("CourNo") or raw.get("SelCourNo"))
                if not name or not teachers or not code or is_excluded_course(name):
                    continue
                department = normalize_space(raw.get("Tea1DepName")) or category_label
                key = (code, normalize_space(raw.get("SelCourNo")), category_code)
                offerings[key] = {
                    "universityId": "nutn",
                    "term": f"{term[:3]}-{term[3]}",
                    "courseCode": code,
                    "name": name,
                    "department": department,
                    "officialSourceUrl": SCHOOLS["nutn"]["index"],
                    "departmentSourceUrl": SCHOOLS["nutn"]["index"],
                    "teacherNames": teachers,
                }
    return list(offerings.values()), len(categories) + 1


def import_nutn() -> tuple[list[dict], dict]:
    categories, catalog_queries = nutn_catalog()
    if not categories:
        raise ValueError("NUTN official course categories are empty")
    current_term = f"{CURRENT_YEAR}1"
    current_rows, current_queries = nutn_term_rows(current_term, categories)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    if not current_teachers:
        raise ValueError("NUTN current official faculty roster is empty")
    rows = list(current_rows)
    report = {
        "universityId": "nutn",
        "status": "imported",
        "officialIndex": SCHOOLS["nutn"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": catalog_queries + current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": [f"{CURRENT_YEAR}-1"],
    }
    history_terms = [term for term in TERMS if term != current_term]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(nutn_term_rows, term, categories): term
            for term in history_terms
        }
        for future in concurrent.futures.as_completed(futures):
            term = futures[future]
            try:
                term_rows, query_count = future.result()
            except Exception as error:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
                report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
                continue
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    return rows, report


def import_nou() -> tuple[list[dict], dict]:
    """Audit NOU's official history without inventing unavailable teachers.

    The public endpoint exposes course titles and descriptions, but teaching
    assignments are only available inside the authenticated student system.
    Course cards require a verified instructor, so the university is seeded and
    the restriction is reported without publishing a fabricated instructor.
    """
    report = {
        "universityId": "nou",
        "status": "restricted",
        "officialIndex": SCHOOLS["nou"]["index"],
        "availableTerms": [],
        "missingTerms": [],
        "officialQueries": 0,
        "parsedCoursesWithoutPublicInstructor": 0,
        "verifiedOfferings": 0,
        "note": "校方公開歷年課程頁未提供授課教師；教師編班需登入，故不建立虛構教師卡。",
    }
    for term in TERMS:
        source = official_url(
            "nou",
            "https://nouapp.nou.edu.tw/depys/courses?"
            + urllib.parse.urlencode({"ayear": term[:3], "sms": term[3]}),
        )
        try:
            page = cached_request(
                "nou",
                f"nou-{term}.html",
                source,
                minimum_size=1_000,
            ).decode("utf-8", "replace")
            course_count = len(set(re.findall(
                r'href=["\']/depys/view\?[^"\']*\bcrsno=([0-9A-Za-z_-]+)',
                page,
                flags=re.I,
            )))
            report["officialQueries"] += 1
            report["parsedCoursesWithoutPublicInstructor"] += course_count
            if course_count:
                report["availableTerms"].append(f"{term[:3]}-{term[3]}")
            else:
                report["missingTerms"].append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            report["missingTerms"].append(f"{term[:3]}-{term[3]}")
            report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
    return [], report


def nuk_department_map() -> dict[str, str]:
    page = cached_request(
        "nuk",
        "nuk-query-index.html",
        SCHOOLS["nuk"]["index"],
        minimum_size=5_000,
    ).decode("utf-8", "replace")
    select = re.search(
        r'<select[^>]+name=["\']Sclass["\'][^>]*>(.*?)</select>',
        page,
        flags=re.I | re.S,
    )
    if not select:
        raise ValueError("NUK department selector is unavailable")
    result = {}
    for code, label in re.findall(
        r'<option[^>]+value=["\']([^"\']*)["\'][^>]*>(.*?)</option>',
        select.group(1),
        flags=re.I | re.S,
    ):
        code = normalize_space(code)
        label = strip_html(label)
        if code and label and "請選擇" not in label:
            result[code] = label
    return result


def nuk_payload(term: str, part: str, page: int) -> bytes:
    return urllib.parse.urlencode({
        "Flag": "1",
        "OpenYear": term[:3],
        "Helf": term[3],
        "Pclass": part,
        "Sclass": "",
        "Yclass": "",
        "SirName": "",
        "Sirno": "",
        "WeekDay": "",
        "Card": "",
        "Subject": "",
        "Language": "",
        "Pre_Cono": "",
        "Coname": "",
        "Page": str(page),
    }).encode()


def nuk_page(term: str, part: str, page: int) -> str:
    result_url = "https://course.nuk.edu.tw/QueryCourse/QueryResult.asp"
    payload = cached_request(
        "nuk",
        f"nuk-{term}-{part}-{page:03d}.html",
        result_url,
        data=nuk_payload(term, part, page),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": SCHOOLS["nuk"]["index"],
        },
        minimum_size=1_000,
    )
    return payload.decode("utf-8", "replace")


def nuk_rows(page: str, department_map: dict[str, str], term: str) -> list[dict]:
    rows = []
    for block in re.findall(r'<tr[^>]+align=["\']center["\'][^>]*>(.*?)</tr>', page, flags=re.I | re.S):
        link = re.search(
            r'<a[^>]+href=["\']([^"\']*tcontent\.asp\?[^"\']+)["\'][^>]*>(.*?)</a>',
            block,
            flags=re.I | re.S,
        )
        if not link:
            continue
        source = official_url("nuk", urljoin("https://course.nuk.edu.tw/QueryCourse/", html.unescape(link.group(1))))
        params = urllib.parse.parse_qs(urlparse(source).query)
        department_code = normalize_space((params.get("Sclass") or [""])[0])
        raw_code = normalize_space((params.get("Cono") or [""])[0])
        name = strip_html(link.group(2))
        teacher_cell = re.search(
            r'<td[^>]*class=["\']NUKEUDC["\'][^>]*>(.*?)</td>',
            block,
            flags=re.I | re.S,
        )
        teachers = split_instructors(strip_html(teacher_cell.group(1)) if teacher_cell else "")
        if not raw_code or not name or is_excluded_course(name) or not teachers:
            continue
        department = department_map.get(department_code, department_code or "共同課程")
        rows.append({
            "universityId": "nuk",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": f"{department_code}-{raw_code}",
            "name": name,
            "department": department,
            "officialSourceUrl": source,
            "departmentSourceUrl": SCHOOLS["nuk"]["index"],
            "teacherNames": teachers,
        })
    return rows


def nuk_term_rows(term: str, department_map: dict[str, str]) -> tuple[list[dict], int]:
    all_rows = []
    query_count = 0
    for part in NUK_PARTS:
        first = nuk_page(term, part, 1)
        query_count += 1
        pages = [int(value) for value in re.findall(r"Submit_Form\((\d+)\)", first) if int(value) >= 1]
        page_count = max(pages, default=1)
        all_rows.extend(nuk_rows(first, department_map, term))
        if page_count <= 1:
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            for page in executor.map(lambda number: nuk_page(term, part, number), range(2, page_count + 1)):
                query_count += 1
                all_rows.extend(nuk_rows(page, department_map, term))
    return all_rows, query_count


def import_nuk() -> tuple[list[dict], dict]:
    department_map = nuk_department_map()
    current_rows, current_queries = nuk_term_rows(f"{CURRENT_YEAR}1", department_map)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    rows = list(current_rows)
    report = {
        "universityId": "nuk",
        "status": "imported",
        "officialIndex": SCHOOLS["nuk"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": current_queries,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
    }
    for term in TERMS:
        if term == f"{CURRENT_YEAR}1":
            continue
        try:
            term_rows, query_count = nuk_term_rows(term, department_map)
            report["officialQueries"] += query_count
            report["parsedOfferings"] += len(term_rows)
            verified = []
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                verified.append({**row, "teacherNames": teachers})
            rows.extend(verified)
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            report["missingTerms"].append(f"{term[:3]}-{term[3]}")
            report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    return rows, report


def nkust_term_rows(term: str) -> list[dict]:
    url = "https://stdsys.nkust.edu.tw/student/Course/QueryCourse/Query"
    common = {
        "Query.StartYear": term[:3],
        "Query.StartSemester": term[3],
        "Query.EndYear": term[:3],
        "Query.EndSemester": term[3],
        "Query.CampusId": "",
        "Query.ProgramId": "",
        "Query.DeptId": "",
        "Query.UnitId": "",
        "Query.ClassYear": "",
        "Query.ClassSeq": "",
        "Query.Keyword": "",
    }
    page_size = 10_000
    result_rows = []
    skip = 0
    total = None
    while total is None or skip < total:
        payload = urllib.parse.urlencode({
            **common,
            "page": str(skip // page_size + 1),
            "pageSize": str(page_size),
            "skip": str(skip),
            "take": str(page_size),
        }).encode()
        response = cached_json_request(
            "nkust",
            f"nkust-{term}-{skip:06d}.json",
            url,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SCHOOLS["nkust"]["index"],
            },
        )
        if not isinstance(response, dict):
            raise ValueError(f"NKUST response is not an object for {term}")
        total = int(response.get("Total") or 0)
        page_rows = response.get("Data") or []
        if not isinstance(page_rows, list):
            raise ValueError(f"NKUST response has no Data list for {term}")
        result_rows.extend(row for row in page_rows if isinstance(row, dict))
        if not page_rows:
            break
        skip += len(page_rows)
    if total and len(result_rows) != total:
        raise ValueError(f"NKUST incomplete response for {term}: {len(result_rows)}/{total}")
    return result_rows


def nkust_normalize_rows(raw_rows: list[dict], term: str) -> list[dict]:
    rows = []
    for raw in raw_rows:
        name = normalize_space(raw.get("SubjectName"))
        teachers = split_instructors(raw.get("TeacherText"))
        permanent_code = normalize_space(raw.get("PerCrsno"))
        offering_code = normalize_space(raw.get("Crsno"))
        source_id = normalize_space(raw.get("Id"))
        if not name or is_excluded_course(name) or not teachers or not source_id:
            continue
        joined = raw.get("JoinCmClass") if isinstance(raw.get("JoinCmClass"), dict) else {}
        unit = joined.get("CmUnit") if isinstance(joined.get("CmUnit"), dict) else {}
        department = normalize_space(
            unit.get("UnitNameFull")
            or unit.get("UnitName")
            or raw.get("ClassText")
            or raw.get("UnitId")
            or "共同課程"
        )
        source = official_url(
            "nkust",
            f"https://stdsys.nkust.edu.tw/student/Course/CourseCommonQuery/_CourseDetailPartialView?id={urllib.parse.quote(source_id)}",
        )
        rows.append({
            "universityId": "nkust",
            "term": f"{term[:3]}-{term[3]}",
            "courseCode": permanent_code or f"{raw.get('UnitId', '')}-{offering_code}",
            "name": name,
            "department": department,
            "officialSourceUrl": source,
            "departmentSourceUrl": SCHOOLS["nkust"]["index"],
            "teacherNames": teachers,
        })
    return rows


def import_nkust() -> tuple[list[dict], dict]:
    current_term = f"{CURRENT_YEAR}1"
    current_raw = nkust_term_rows(current_term)
    current_rows = nkust_normalize_rows(current_raw, current_term)
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    rows = list(current_rows)
    report = {
        "universityId": "nkust",
        "status": "imported",
        "officialIndex": SCHOOLS["nkust"]["index"],
        "availableTerms": [f"{CURRENT_YEAR}-1"],
        "missingTerms": [],
        "officialQueries": 1,
        "parsedOfferings": len(current_rows),
        "rejectedWithoutCurrentFaculty": 0,
    }
    for term in TERMS:
        if term == current_term:
            continue
        try:
            raw_rows = nkust_term_rows(term)
            term_rows = nkust_normalize_rows(raw_rows, term)
            report["officialQueries"] += max(1, (len(raw_rows) + 9_999) // 10_000)
            report["parsedOfferings"] += len(term_rows)
            verified = []
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                verified.append({**row, "teacherNames": teachers})
            rows.extend(verified)
            report["availableTerms"].append(f"{term[:3]}-{term[3]}")
        except Exception as error:
            report["missingTerms"].append(f"{term[:3]}-{term[3]}")
            report.setdefault("fetchErrors", []).append(f"{term}: {type(error).__name__}")
    report["availableTerms"] = sorted(set(report["availableTerms"]))
    return rows, report


def npu_post(filename: str, fields: dict[str, str]) -> str:
    payload = urllib.parse.urlencode(fields).encode()
    return cached_request(
        "npu",
        filename,
        SCHOOLS["npu"]["index"],
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": SCHOOLS["npu"]["index"],
        },
        timeout=120,
        minimum_size=1_000,
    ).decode("utf-8", "replace")


def npu_unit_map() -> dict[tuple[str, str], str]:
    index = cached_request(
        "npu",
        "npu-index.html",
        SCHOOLS["npu"]["index"],
        minimum_size=2_000,
    ).decode("utf-8", "replace")
    degree_select = re.search(
        r'<select[^>]+name=["\']dgr["\'][^>]*>(.*?)</select>',
        index,
        flags=re.I | re.S,
    )
    if not degree_select:
        raise ValueError("NPU degree selector is unavailable")
    degree_codes = [
        normalize_space(code)
        for code in re.findall(
            r'<option[^>]+value=["\']([^"\']+)["\']',
            degree_select.group(1),
            flags=re.I,
        )
        if normalize_space(code)
    ]
    result = {}
    for degree_code in degree_codes:
        page = npu_post(
            f"npu-units-{degree_code}.html",
            {"gck": "0", "years": "", "dgr": degree_code, "unit": "", "yms": "", "keyword": ""},
        )
        unit_select = re.search(
            r'<select[^>]+name=["\']unit["\'][^>]*>(.*?)</select>',
            page,
            flags=re.I | re.S,
        )
        if not unit_select:
            continue
        for unit_code, label in re.findall(
            r'<option[^>]+value=["\']([^"\']+)["\'][^>]*>(.*?)</option>',
            unit_select.group(1),
            flags=re.I | re.S,
        ):
            unit_code = normalize_space(unit_code)
            label = strip_html(label)
            if unit_code and label and "系所" not in label:
                result[(degree_code, unit_code)] = label
    return result


def npu_year_rows(year: int, unit_map: dict[tuple[str, str], str]) -> list[dict]:
    page = npu_post(
        f"npu-{year}-all.html",
        {"gck": "1", "years": str(year), "dgr": "", "unit": "", "yms": "", "keyword": ""},
    )
    rows = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.I | re.S):
        link = re.search(
            r'<a[^>]+data-url=["\']([^"\']*course-cont\.asp\?[^"\']+)["\'][^>]*>(.*?)</a>',
            block,
            flags=re.I | re.S,
        )
        if not link:
            continue
        source = official_url(
            "npu",
            urljoin("https://cmap.npu.edu.tw/", html.unescape(link.group(1))),
        )
        params = urllib.parse.parse_qs(urlparse(source).query)
        degree_code = normalize_space((params.get("dgr_id") or [""])[0])
        unit_code = normalize_space((params.get("unt_id") or [""])[0])
        subject_id = normalize_space((params.get("sub_id") or [""])[0])
        cells = re.findall(r"<td[^>]*>(.*?)</td>", block, flags=re.I | re.S)
        if len(cells) < 8:
            continue
        name = strip_html(link.group(2))
        teachers = split_instructors(strip_html(cells[5]))
        semester_text = strip_html(cells[6])
        semester = "1" if "上學期" in semester_text else "2" if "下學期" in semester_text else ""
        if not subject_id or not semester or not name or is_excluded_course(name) or not teachers:
            continue
        rows.append({
            "universityId": "npu",
            "term": f"{year}-{semester}",
            "courseCode": f"{degree_code}-{unit_code}-{subject_id}",
            "name": name,
            "department": unit_map.get((degree_code, unit_code), unit_code or "共同課程"),
            "officialSourceUrl": source,
            "departmentSourceUrl": SCHOOLS["npu"]["index"],
            "teacherNames": teachers,
        })
    return rows


def import_npu() -> tuple[list[dict], dict]:
    unit_map = npu_unit_map()
    by_year = {year: npu_year_rows(year, unit_map) for year in range(EARLIEST_YEAR, CURRENT_YEAR + 1)}
    current_rows = [row for row in by_year[CURRENT_YEAR] if row["term"] == f"{CURRENT_YEAR}-1"]
    current_teachers = {teacher for row in current_rows for teacher in row["teacherNames"]}
    allowed_terms = {f"{term[:3]}-{term[3]}" for term in TERMS}
    rows = []
    report = {
        "universityId": "npu",
        "status": "imported",
        "officialIndex": SCHOOLS["npu"]["index"],
        "availableTerms": [],
        "missingTerms": [],
        "officialQueries": len(by_year) + len({key[0] for key in unit_map}),
        "parsedOfferings": 0,
        "rejectedWithoutCurrentFaculty": 0,
    }
    for term in sorted(allowed_terms):
        year = int(term[:3])
        term_rows = [row for row in by_year[year] if row["term"] == term]
        report["parsedOfferings"] += len(term_rows)
        if not term_rows:
            report["missingTerms"].append(term)
            continue
        for row in term_rows:
            teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
            if not teachers:
                report["rejectedWithoutCurrentFaculty"] += 1
                continue
            rows.append({**row, "teacherNames": teachers})
        report["availableTerms"].append(term)
    return rows, report


def nqu_get(filename: str, url: str) -> str:
    return cached_request(
        "nqu",
        filename,
        url,
        timeout=120,
        minimum_size=1_000,
    ).decode("utf-8", "replace")


def nqu_course_rows(page: str, department: str, department_code: str) -> list[dict]:
    rows = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.I | re.S):
        link = re.search(
            r'<a[^>]+href=["\'](https://ecampus\.nqu\.edu\.tw/eCampus3P/Learn/public/teachIntro\.aspx\?[^"\']+)["\'][^>]*>(.*?)</a>',
            block,
            flags=re.I | re.S,
        )
        if not link:
            continue
        source = official_url("nqu", html.unescape(link.group(1)))
        params = urllib.parse.parse_qs(urlparse(source).query)
        full_code = normalize_space((params.get("CourseNo") or [""])[0])
        year = normalize_space((params.get("year") or [""])[0])
        semester = normalize_space((params.get("sms") or [""])[0])
        cells = re.findall(r"<td[^>]*>(.*?)</td>", block, flags=re.I | re.S)
        if len(cells) < 6:
            continue
        name = strip_html(link.group(2))
        teachers = split_instructors(strip_html(cells[5]))
        permanent_code = full_code.split("-")[-2] if len(full_code.split("-")) >= 2 else full_code
        if (
            not full_code
            or not permanent_code
            or not year.isdigit()
            or semester not in {"1", "2"}
            or not name
            or is_excluded_course(name)
            or not teachers
        ):
            continue
        rows.append({
            "universityId": "nqu",
            "term": f"{year}-{semester}",
            "courseCode": f"{department_code}-{permanent_code}",
            "name": name,
            "department": department,
            "officialSourceUrl": source,
            "departmentSourceUrl": SCHOOLS["nqu"]["index"],
            "teacherNames": teachers,
        })
    return rows


def nqu_year_rows(year: int) -> tuple[list[dict], int]:
    base = "https://ecampus.nqu.edu.tw/CoreCom/Home/"
    index_url = f"{base}Index.aspx?year={year}"
    index = nqu_get(f"nqu-{year}-index.html", index_url)
    college_links = []
    for href, label in re.findall(
        r'<a[^>]+href=["\']((?:CollegeIndex|OtherCollegeIndex)\.aspx\?[^"\']+)["\'][^>]*>(.*?)</a>',
        index,
        flags=re.I | re.S,
    ):
        college_links.append((urljoin(base, html.unescape(href)), strip_html(label)))
    if not college_links:
        raise ValueError(f"NQU college index is empty for {year}")

    jobs = []
    direct_pages = []
    for number, (college_url, college_name) in enumerate(college_links):
        college_page = nqu_get(f"nqu-{year}-college-{number:02d}.html", college_url)
        if "OtherCollegeIndex.aspx" in college_url:
            college_params = urllib.parse.parse_qs(urlparse(college_url).query)
            direct_pages.append((college_page, college_name, normalize_space((college_params.get("acronym") or ["XC"])[0])))
            continue
        for href, label in re.findall(
            r'<a[^>]+href=["\']DepIndex\.aspx\?([^"\']+)["\'][^>]*>(.*?)</a>',
            college_page,
            flags=re.I | re.S,
        ):
            params = urllib.parse.parse_qs(html.unescape(href))
            department_id = normalize_space((params.get("deptid") or [""])[0])
            department_code = normalize_space((params.get("deptno") or [""])[0])
            if not department_id or not department_code:
                continue
            course_url = (
                f"{base}DepCourseIndex.aspx?deptid={urllib.parse.quote(department_id)}"
                f"&deptno={urllib.parse.quote(department_code)}&year={year}"
            )
            jobs.append((course_url, strip_html(label), department_code))

    def fetch(job: tuple[str, str, str]) -> tuple[str, str, str]:
        source, department, department_code = job
        token = hashlib.sha256(source.encode()).hexdigest()[:16]
        return nqu_get(f"nqu-{year}-department-{token}.html", source), department, department_code

    rows = []
    for page, department, code in direct_pages:
        rows.extend(nqu_course_rows(page, department, code or "XC"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for page, department, code in executor.map(fetch, jobs):
            rows.extend(nqu_course_rows(page, department, code))
    return rows, 1 + len(college_links) + len(jobs)


def import_nqu() -> tuple[list[dict], dict]:
    by_year = {}
    query_count = 0
    for year in range(EARLIEST_YEAR, 115):
        rows, queries = nqu_year_rows(year)
        by_year[year] = rows
        query_count += queries
    latest_rows = by_year[114]
    current_teachers = {teacher for row in latest_rows for teacher in row["teacherNames"]}
    rows = []
    report = {
        "universityId": "nqu",
        "status": "partial",
        "officialIndex": SCHOOLS["nqu"]["index"],
        "availableTerms": [],
        "missingTerms": ["115-1"],
        "officialQueries": query_count,
        "parsedOfferings": 0,
        "rejectedWithoutCurrentFaculty": 0,
        "currentRosterEvidenceTerms": ["114-1", "114-2"],
        "note": "校方 CoreCom 實際開課資料目前公開至 114-2；115-1 未以免驗證碼批次來源公開。",
    }
    for year, year_rows in sorted(by_year.items()):
        for term in (f"{year}-1", f"{year}-2"):
            term_rows = [row for row in year_rows if row["term"] == term]
            report["parsedOfferings"] += len(term_rows)
            if not term_rows:
                report["missingTerms"].append(term)
                continue
            for row in term_rows:
                teachers = [teacher for teacher in row["teacherNames"] if teacher in current_teachers]
                if not teachers:
                    report["rejectedWithoutCurrentFaculty"] += 1
                    continue
                rows.append({**row, "teacherNames": teachers})
            report["availableTerms"].append(term)
    report["missingTerms"] = sorted(set(report["missingTerms"]))
    return rows, report


def course_id(university_id: str, course_code: str) -> str:
    digest = hashlib.sha256(f"{university_id}\0{course_code}".encode()).hexdigest()[:16]
    return f"course-{university_id}-{digest}"


def deduplicate(offerings: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for row in offerings:
        # Schools that stack the Chinese name, the English translation and the
        # merged-class note in one schedule cell are published under the first
        # official line only.
        row = {**row, "name": official_course_name(row["name"])}
        if not row["name"] or is_excluded_course(row["name"]):
            continue
        key = (row["universityId"], row["courseCode"])
        current = merged.get(key)
        if current is None:
            current = {
                **row,
                "instructors": {},
                "instructorTerms": {},
                "offeredTerms": set(),
                "departments": {value for value in row["department"].split("/") if value},
            }
            merged[key] = current
        elif row["term"] > current["term"]:
            for field in ("term", "name", "officialSourceUrl", "departmentSourceUrl"):
                current[field] = row[field]
        current["departments"].update(value for value in row["department"].split("/") if value)
        current["offeredTerms"].add(row["term"])
        for teacher in row["teacherNames"]:
            if row["term"] >= current["instructorTerms"].get(teacher, ""):
                current["instructors"][teacher] = row.get("teacherSourceUrls", {}).get(
                    teacher,
                    row["officialSourceUrl"],
                )
                current["instructorTerms"][teacher] = row["term"]

    courses = []
    for row in merged.values():
        terms = sorted(row["offeredTerms"])
        courses.append({
            "id": course_id(row["universityId"], row["courseCode"]),
            "universityId": row["universityId"],
            "term": row["term"],
            "semester": row["term"].rsplit("-", 1)[-1],
            "firstTerm": terms[0],
            "lastTerm": terms[-1],
            "offeredTerms": terms,
            "courseCode": row["courseCode"],
            "name": row["name"],
            "department": "/".join(sorted(row["departments"])) or row["department"],
            "officialSourceUrl": row["officialSourceUrl"],
            "departmentSourceUrl": row["departmentSourceUrl"],
            "instructors": [
                {"name": name, "officialSourceUrl": source}
                for name, source in sorted(row["instructors"].items())
            ],
        })
    return sorted(courses, key=lambda row: (row["universityId"], row["department"], row["name"], row["courseCode"]))


def sql_quote(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def department_id(university_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{university_id}\0{name}".encode()).hexdigest()[:16]
    return f"dept-{university_id}-{digest}"


def committed_migration_names() -> set[str]:
    """List migrations in HEAD, independently of uncommitted index/worktree state."""
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


def write_migrations(
    courses: list[dict],
    checked_at: str,
    batch_id: str = BATCH_ID,
    target_schools: tuple[str, ...] = (),
) -> list[str]:
    """Write one immutable migration batch.

    ``target_schools`` limits the official rows this batch rebuilds, so a later
    batch that only covers the schools a previous run could not reach never
    deletes course rows an earlier committed batch already published.
    """
    target_schools = tuple(sorted(target_schools or SCHOOLS))
    unknown = [school for school in target_schools if school not in SCHOOLS]
    if unknown:
        raise ValueError(f"unknown target schools: {', '.join(unknown)}")
    school_list = ", ".join(sql_quote(value) for value in target_schools)
    timestamp = checked_at.replace("+00:00", ".000Z")
    blocks = []

    for school_id, school in SCHOOLS.items():
        blocks.append(
            "INSERT INTO universities (id, name, short_name, city, district, latitude, longitude, address, created_at) VALUES ("
            + ", ".join(sql_quote(value) for value in (
                school_id,
                school["name"],
                school["shortName"],
                school["city"],
                school["district"],
                school["latitude"],
                school["longitude"],
                school["address"],
                timestamp,
            ))
            + ") ON CONFLICT(id) DO UPDATE SET name=excluded.name, short_name=excluded.short_name, city=excluded.city, district=excluded.district, latitude=excluded.latitude, longitude=excluded.longitude, address=excluded.address;\n"
            "--> statement-breakpoint\n"
        )

    departments = {}
    for row in courses:
        departments[(row["universityId"], row["department"])] = row["departmentSourceUrl"]
    for start in range(0, len(departments), 30):
        values = []
        for (university_id, name), source in list(sorted(departments.items()))[start:start + 30]:
            values.append("(" + ", ".join(sql_quote(value) for value in (
                department_id(university_id, name),
                university_id,
                "",
                name,
                "academic-unit",
                source,
                timestamp,
                timestamp,
            )) + ")")
        blocks.append("\n".join([
            "INSERT INTO academic_departments (id, university_id, college, name, unit_type, official_source_url, created_at, updated_at) VALUES",
            ",\n".join(values),
            "ON CONFLICT(university_id, name) DO UPDATE SET official_source_url=excluded.official_source_url, updated_at=excluded.updated_at;",
            "--> statement-breakpoint\n",
        ]))

    blocks.append(
        "-- Preserve every published rating, but rebuild every official instructor link from current evidence.\n"
        f"DELETE FROM course_instructors WHERE course_id IN (SELECT c.id FROM courses c WHERE c.university_id IN ({school_list}) AND c.source_type='official');\n"
        "--> statement-breakpoint\n"
        "-- Rated stale courses remain as rating parents without a visible stale instructor relationship.\n"
        f"DELETE FROM courses WHERE university_id IN ({school_list}) AND source_type='official' AND NOT EXISTS (SELECT 1 FROM course_ratings cr WHERE cr.course_id=courses.id);\n"
        "--> statement-breakpoint\n"
    )

    for start in range(0, len(courses), 20):
        values = []
        for row in courses[start:start + 20]:
            values.append("(" + ", ".join(sql_quote(value) for value in (
                row["id"], row["universityId"], row["term"], row["firstTerm"], row["lastTerm"],
                ",".join(row["offeredTerms"]), row["semester"], row["courseCode"], row["name"],
                row["department"], row["officialSourceUrl"], row["departmentSourceUrl"], "official",
                timestamp, timestamp,
            )) + ")")
        blocks.append("\n".join([
            "INSERT INTO courses (id, university_id, term, first_term, last_term, offered_terms, semester, course_code, name, department, official_source_url, department_source_url, source_type, created_at, updated_at) VALUES",
            ",\n".join(values),
            "ON CONFLICT(id) DO UPDATE SET term=excluded.term, first_term=excluded.first_term, last_term=excluded.last_term, offered_terms=excluded.offered_terms, semester=excluded.semester, course_code=excluded.course_code, name=excluded.name, department=excluded.department, official_source_url=excluded.official_source_url, department_source_url=excluded.department_source_url, source_type='official', updated_at=excluded.updated_at;",
            "--> statement-breakpoint\n",
        ]))

    instructor_rows = [(row, instructor) for row in courses for instructor in row["instructors"]]
    for start in range(0, len(instructor_rows), 40):
        values = []
        for row, instructor in instructor_rows[start:start + 40]:
            values.append("(" + ", ".join(sql_quote(value) for value in (
                row["id"], instructor["name"], None, instructor["officialSourceUrl"], timestamp,
            )) + ")")
        blocks.append("\n".join([
            "INSERT INTO course_instructors (course_id, instructor_name, professor_id, official_source_url, created_at) VALUES",
            ",\n".join(values),
            "ON CONFLICT(course_id, instructor_name) DO UPDATE SET official_source_url=excluded.official_source_url;",
            "--> statement-breakpoint\n",
        ]))

    blocks.append(
        "INSERT INTO app_runtime_state (key, value, updated_at) VALUES "
        f"({sql_quote(batch_id)}, {sql_quote(checked_at)}, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;\n"
        "--> statement-breakpoint\nPRAGMA optimize;\n"
    )

    batch_name_pattern = re.compile(
        rf"^\d{{4}}_{re.escape(batch_id)}_part_\d+\.sql$"
    )
    committed_batch = sorted(
        name for name in committed_migration_names()
        if batch_name_pattern.fullmatch(name)
    )
    if committed_batch:
        raise RuntimeError(
            f"{batch_id} already has committed migrations ({', '.join(committed_batch)}); "
            "pass a new --batch-id before generating another immutable batch"
        )

    pattern = f"[0-9][0-9][0-9][0-9]_{batch_id}_part_*.sql"
    current_batch = list(MIGRATIONS.glob(pattern))
    current_names = {path.name for path in current_batch}
    other_numbers = [
        int(match.group(1))
        for path in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if path.name not in current_names and (match := re.match(r"(\d{4})_", path.name))
    ]
    start_number = max(other_numbers, default=0) + 1
    for path in current_batch:
        path.unlink()

    header = "-- Generated from university-owned public course sources only.\n"
    max_bytes = 850 * 1024
    files = []
    current = header
    for block in blocks:
        if len(current.encode("utf-8")) + len(block.encode("utf-8")) > max_bytes and current != header:
            number = start_number + len(files)
            name = f"{number:04d}_{batch_id}_part_{len(files) + 1:02d}.sql"
            (MIGRATIONS / name).write_text(current, encoding="utf-8")
            files.append(name)
            current = header
        current += block
    if current != header:
        number = start_number + len(files)
        name = f"{number:04d}_{batch_id}_part_{len(files) + 1:02d}.sql"
        (MIGRATIONS / name).write_text(current, encoding="utf-8")
        files.append(name)
    return files


IMPORTERS = {
    "ntnu": lambda: import_ntnu(),
    "ntcu": lambda: import_ntcu(),
    "ntue": lambda: import_ntue(),
    "ntou": lambda: import_ntou(),
    "ntpu": lambda: import_ntpu(),
    "nttu": lambda: import_nttu(),
    "ntub": lambda: import_ntub(),
    "ntunhs": lambda: import_ntunhs(),
    "ntus": lambda: import_ntus(),
    "tnua": lambda: import_tnua(),
    "tnnua": lambda: import_tnnua(),
    "ntua": lambda: import_ntua(),
    "nfu": lambda: import_nfu(),
    "ncue": lambda: import_ncue(),
    "nknu": lambda: import_nknu(),
    "ncyu": lambda: import_ncyu(),
    "yuntech": lambda: import_yuntech(),
    "utaipei": lambda: import_utaipei(),
    "nutc": lambda: import_nutc(),
    "nuk": lambda: import_nuk(),
    "nkuht": lambda: import_nkuht(),
    "nkust": lambda: import_nkust(),
    "npu": lambda: import_npu(),
    "npust": lambda: import_npust(),
    "nptu": lambda: import_nptu(),
    "nqu": lambda: import_nqu(),
    "nutn": lambda: import_nutn(),
    "nou": lambda: import_nou(),
}


def merge_report(payload: dict) -> dict:
    """Keep audited schools from earlier committed batches in the same report."""
    path = DB / "place-name-course-report.generated.json"
    if not path.exists():
        return payload
    previous = json.loads(path.read_text(encoding="utf-8"))
    covered = {report["universityId"] for report in payload["schools"]}
    retained = [
        report for report in previous.get("schools", [])
        if report["universityId"] not in covered
    ]
    payload["schools"] = sorted(
        retained + payload["schools"],
        key=lambda report: report["universityId"],
    )
    payload["batches"] = sorted(
        {*previous.get("batches", []), *({previous["batchId"]} if previous.get("batchId") else set()), payload["batchId"]}
    )
    payload["previousMigrationFiles"] = sorted({
        *previous.get("previousMigrationFiles", []),
        *previous.get("migrationFiles", []),
    })
    payload["courseCount"] = payload["batchCourseCount"] + sum(
        report.get("verifiedCourses", 0) for report in retained
    )
    return payload


def normalize_status(report: dict) -> dict:
    """Never advertise full coverage while audited terms are still missing."""
    if report.get("status") == "imported" and report.get("missingTerms"):
        report["status"] = "partial"
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        default="",
        help="comma separated school ids to import; defaults to every audited school",
    )
    parser.add_argument(
        "--batch-id",
        default=BATCH_ID,
        help="immutable migration batch name; a committed batch is never rewritten",
    )
    arguments = parser.parse_args()
    selected = [value.strip() for value in arguments.only.split(",") if value.strip()]
    unknown = [value for value in selected if value not in IMPORTERS]
    if unknown:
        parser.error(f"unknown school ids: {', '.join(unknown)}")
    targets = selected or list(IMPORTERS)

    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    offerings = []
    reports = []
    for school_id in targets:
        try:
            rows, report = IMPORTERS[school_id]()
        except Exception as error:
            # A school whose official endpoint is down is reported as such
            # instead of aborting the audited batch or inventing rows for it.
            rows = []
            report = {
                "universityId": school_id,
                "status": "unreachable",
                "officialIndex": SCHOOLS[school_id]["index"],
                "availableTerms": [],
                "missingTerms": [f"{term[:3]}-{term[3]}" for term in TERMS],
                "officialQueries": 0,
                "parsedOfferings": 0,
                "rejectedWithoutCurrentFaculty": 0,
                "currentRosterEvidenceTerms": [],
                "fetchErrors": [f"{type(error).__name__}: {normalize_space(error)[:200]}"],
                "note": "校方公開課程端點在稽核當下無法連線；不改用第三方鏡像或快取補資料。",
            }
        offerings.extend(rows)
        reports.append(normalize_status(report))
        print(
            f"{report['universityId']}: {len(rows)} verified offerings ({report['status']})",
            flush=True,
        )
    courses = deduplicate(offerings)
    by_school = defaultdict(int)
    for row in courses:
        by_school[row["universityId"]] += 1
    for report in reports:
        report["verifiedCourses"] = by_school[report["universityId"]]
    migration_files = write_migrations(
        courses,
        checked_at,
        batch_id=arguments.batch_id,
        target_schools=tuple(targets),
    )
    payload = merge_report({
        "policy": {
            "officialUniversityDomainsOnly": True,
            "requiresCurrentOfficialScheduleEvidence": True,
            "inactiveOrUnverifiedInstructorsPublished": False,
            "excludedCourseNames": ["專題研究", "Special Research Project"],
        },
        "checkedAt": checked_at,
        "batchId": arguments.batch_id,
        "batchSchools": sorted(targets),
        "batchCourseCount": len(courses),
        "courseCount": len(courses),
        "schools": reports,
        "migrationFiles": migration_files,
    })
    (DB / "place-name-course-report.generated.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"courses": len(courses), "bySchool": dict(by_school)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
