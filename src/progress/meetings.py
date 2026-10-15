"""拆解會議紀錄（純文字）：段落、案名、日期、階段字眼。只讀，不改原檔，不用大模型。"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from shared.config import load_yaml

BULLET = re.compile(
    r"^\s*(?:[-*•➢⚫▪◦o]\s+|[-*•➢⚫▪◦]|\d{1,2}[.、)]\s*|[一二三四五六七八九十]+、\s*)"
)
NUMBERED_HEADING = re.compile(r"^\s*[一二三四五六七八九十]+、")
LABEL = re.compile(r"^([^：:]{1,25})[：:]\s*(.*)$")
FILE_DATE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
TEXT_DATE = re.compile(r"會議日期[^：:]*[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

_Y = r"(\d{4}|1\d{2})"  # 西元或民國年
_FULL = re.compile(_Y + r"\s*[/年-]\s*(\d{1,2})\s*[/月-]\s*(\d{1,2})\s*[日號]?")
_Y_APPROX = re.compile(_Y + r"\s*年\s*(\d{1,2})\s*月\s*(底|初|中旬|上旬|下旬|中)?")
_Y_END = re.compile(_Y + r"\s*年底")
_MD_CN = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日號]")
_MD = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/])")
_APPROX = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(底|初|中旬|上旬|下旬|中)")
_MONTH = re.compile(r"(?<![\d/])(\d{1,2})\s*月(?!\s*\d)")
_YEAR_END = re.compile(r"年底")
_YEAR_WORD = re.compile(r"(明年|今年|後年)")
UNSURE_DAYS = 60  # 推定年份後，日期比會議早超過這麼多天，代表可能是跨年，不猜


@dataclass(frozen=True)
class Approx:
    label: str  # 例：2026年10月底
    end: dt.date  # 這段時間的最後一天，用來判斷是否在看板日期之後


@dataclass
class Line:
    no: int  # 第幾行（從 1 起算）
    text: str
    section: str = ""
    skipped: str = ""  # 不讀的原因：section（財務、人事、行政段落）或 word（這一行有略過字眼）
    heading: str = ""  # strong（正式標題）、weak（短的一行字）
    label: str = ""
    label_only: bool = False  # 「名稱：」後面沒有內容，底下的條目屬於這個名稱
    exact: list[dt.date] = field(default_factory=list)
    approx: list[Approx] = field(default_factory=list)
    unsure: list[str] = field(default_factory=list)  # 年份不確定的日期寫法
    stage_words: list[str] = field(default_factory=list)


@dataclass
class Meeting:
    path: Path
    date: dt.date | None
    lines: list[Line] = field(default_factory=list)
    problem: str = ""  # 無法使用的原因（白話）
    text_date: dt.date | None = None


@dataclass(frozen=True)
class MeetingRules:
    folder: str
    file_glob: str
    aliases_file: str
    skip_section_words: tuple[str, ...]
    skip_line_words: tuple[str, ...]
    generic_words: tuple[str, ...]
    stage_words: tuple[str, ...]
    done_words: tuple[str, ...]

    @classmethod
    def load(cls, config_dir: Path | None = None) -> MeetingRules:
        c = load_yaml("meetings.yaml", config_dir)
        return cls(
            folder=c["folder"],
            file_glob=c.get("file_glob", "*.txt"),
            aliases_file=c["aliases_file"],
            skip_section_words=tuple(str(x) for x in c.get("skip_section_words") or ()),
            skip_line_words=tuple(str(x) for x in c.get("skip_line_words") or ()),
            generic_words=tuple(str(x) for x in c.get("generic_words") or ()),
            stage_words=tuple(str(x) for x in c.get("stage_words") or ()),
            done_words=tuple(str(x) for x in c.get("done_words") or ()),
        )


def norm(s: str) -> str:
    """全形半形統一、去空白、英文小寫。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)).lower().replace("臺", "台")


def _safe(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _year(y: str) -> int:
    n = int(y)
    return n + 1911 if n < 1000 else n  # 民國年


def _approx(year: int, mo: int, part: str | None) -> Approx | None:
    if not 1 <= mo <= 12:
        return None
    last = calendar.monthrange(year, mo)[1]
    end = {"初": 10, "上旬": 10, "中": 20, "中旬": 20}.get(part or "", last)
    return Approx(f"{year}年{mo}月{part or ''}", dt.date(year, mo, end))


def _segment(t, year, may_cross, floor, exact, approx, unsure) -> None:
    """處理一段文字（同一個推定年份）。已認出的日期會被挖掉，避免重複計算。"""

    def take(pattern: re.Pattern, fn) -> None:
        nonlocal t
        out, last = [], 0
        for m in pattern.finditer(t):
            fn(m)
            out.append(t[last : m.start()] + " " * (m.end() - m.start()))
            last = m.end()
        t = "".join(out) + t[last:]

    def inferred(d, raw: str) -> None:
        if d is None:
            return
        end = d.end if isinstance(d, Approx) else d
        if may_cross and end < floor:
            unsure.append(raw.strip())
        else:
            (approx if isinstance(d, Approx) else exact).append(d)

    take(_FULL, lambda m: exact.append(_safe(_year(m[1]), int(m[2]), int(m[3]))))
    take(_Y_APPROX, lambda m: approx.append(_approx(_year(m[1]), int(m[2]), m[3])))
    take(
        _Y_END, lambda m: approx.append(Approx(f"{_year(m[1])}年底", dt.date(_year(m[1]), 12, 31)))
    )
    take(_MD_CN, lambda m: inferred(_safe(year, int(m[1]), int(m[2])), m[0]))
    take(_MD, lambda m: inferred(_safe(year, int(m[1]), int(m[2])), m[0]))
    take(_APPROX, lambda m: inferred(_approx(year, int(m[1]), m[2]), m[0]))
    take(_MONTH, lambda m: inferred(_approx(year, int(m[1]), None), m[0]))
    take(_YEAR_END, lambda m: approx.append(Approx(f"{year}年底", dt.date(year, 12, 31))))


def extract_dates(
    text: str, meeting_date: dt.date
) -> tuple[list[dt.date], list[Approx], list[str]]:
    """找出一行裡的日期，回傳 (明確日期, 約略時程, 年份不確定的寫法)。

    - 寫明年份的（2027/3/1、2027 年 3 月、116 年底）照寫的年份。
    - 沒寫年份的＝會議那一年；寫在「明年」之後的加一年、「後年」加兩年。
    - 推定的日期比會議早超過 60 天（例如 12 月的會議寫「1/20」），可能是跨年，不猜，列為年份不確定。
    - 不認得的寫法（10.25、2/30）不猜。
    """
    exact: list[dt.date] = []
    approx: list[Approx] = []
    unsure: list[str] = []
    floor = meeting_date - dt.timedelta(days=UNSURE_DAYS)
    shift = 0
    for seg in _YEAR_WORD.split(unicodedata.normalize("NFKC", text)):
        if seg in ("明年", "今年", "後年"):
            shift = {"今年": 0, "明年": 1, "後年": 2}[seg]
            continue
        _segment(seg, meeting_date.year + shift, shift == 0, floor, exact, approx, unsure)
    exact = sorted({d for d in exact if d is not None})
    approx = [a for a in approx if a is not None]
    return exact, approx, unsure


def case_keys(name: str, generic: tuple[str, ...] | list[str]) -> list[str]:
    """看板案名拆成可比對的關鍵字（去掉籠統字詞、太短的字）。"""
    gen = {norm(g) for g in generic}
    parts = re.split(r"[、／/（）()：:\s與]+", unicodedata.normalize("NFKC", name))
    keys = []
    for p in parts:
        k = norm(p)
        if len(k) >= 2 and k not in gen and not k.isdigit():
            keys.append(k)
    return keys


def match_cases(
    text: str, cases: list[str], aliases: dict[str, str], generic: tuple[str, ...] | list[str]
) -> set[str]:
    """回傳這段文字提到的看板案名。對應表、完整案名優先；只對到一部分時，對到幾案就回傳幾案（不猜）。"""
    t = norm(text)
    full = {aliases[a] for a in aliases if norm(a) and norm(a) in t}
    gen = {norm(g) for g in generic}
    full |= {c for c in cases if norm(c) not in gen and norm(c) in t}
    if full:
        return full
    parts = {c for c in cases if any(k in t for k in case_keys(c, generic))}
    if parts or len(t) < 2 or len(t) > 12 or t in gen:
        return parts
    # 短的名稱（例如「名稱：」的名稱）被看板案名包含，也算對到，例如「甲慈善」→「甲慈善醫院」
    return {c for c in cases if t in norm(c)}


AMOUNT = re.compile(r"\d[\d,.]*\s*[萬億](?![次人])")


def _heading(s: str) -> str:
    """回傳 strong（# 開頭、一、二、、以冒號結尾）、weak（短的一行字）或空字串。"""
    if not s or BULLET.match(s) and not NUMBERED_HEADING.match(s):
        return ""
    if s.startswith("#") or NUMBERED_HEADING.match(s) or s.endswith(("：", ":")):
        return "strong"
    if len(s) <= 20 and not re.search(r"[：:]", s) and not re.search(r"\d", s):
        return "weak"
    return ""


def _usable_label(label: str, rules: MeetingRules) -> bool:
    """「名稱：內容」的名稱看起來像案名才用：不是日期時間、不是句子、不是階段字眼。"""
    return not (
        re.search(r"\d\s*[/:：]|\d{1,2}\s*月", label)
        or re.search(r"[，。,；;]", label)
        or len(norm(label)) > 15
        or any(w in label for w in rules.stage_words)
        or label in ("進行中", "已結案", "新案", "進度", "日期", "時間", "地點", "場地", "展期")
    )


def parse_meeting(path: Path, rules: MeetingRules, names_case=lambda s: False) -> Meeting:
    """names_case(文字)：這段文字是否提到看板上的案子。標題提到案子時，即使含略過字眼也不略過整段。"""
    m = FILE_DATE.search(path.name)
    date = _safe(*(int(x) for x in m.groups())) if m else None
    if date is None:
        return Meeting(path, None, problem="檔名沒有日期（需要 8 碼，例如 20260907），未使用")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return Meeting(path, date, problem="不是 UTF-8 編碼，請用記事本另存為 UTF-8，未使用")
    if not raw.strip():
        return Meeting(path, date, problem="空白檔案，未使用")
    meeting = Meeting(path, date)
    section = ""
    skip = ""  # 目前略過的段落是由 strong 或 weak 標題開始的
    for no, text in enumerate(raw.splitlines(), start=1):
        s = text.strip()
        if not s:
            continue
        td = TEXT_DATE.search(s)
        if td and meeting.text_date is None:
            meeting.text_date = _safe(*(int(x) for x in td.groups()))
        ln = Line(no, s)
        kind = _heading(s)
        if kind:
            ln.heading = kind
            title = s.lstrip("#").rstrip("：:").strip()
            is_skip = any(w in title for w in rules.skip_section_words) and not names_case(title)
            if is_skip:
                section, skip = title, (skip if skip == "strong" else kind)
            elif kind == "strong" or skip != "strong":
                # 財務段落只有遇到下一個正式標題才結束，夾在中間的短句不會解除略過
                section, skip = title, ""
        ln.section = section
        if skip:
            ln.skipped = "section"
        elif not kind and (any(w in s for w in rules.skip_line_words) or AMOUNT.search(s)):
            ln.skipped = "word"
        body = BULLET.sub("", s, count=1).lstrip("#").strip()
        lm = LABEL.match(body)
        if lm and not ln.heading and _usable_label(lm[1].strip(), rules):
            ln.label = lm[1].strip()
            ln.label_only = not lm[2].strip()
        if not ln.skipped:
            ln.exact, ln.approx, ln.unsure = extract_dates(s, date)
            ln.stage_words = [w for w in rules.stage_words if w in s]
            # 長的字眼已涵蓋短的（例如「已結案」含「結案」），只留長的
            ln.stage_words = [
                w for w in ln.stage_words if not any(w != o and w in o for o in ln.stage_words)
            ]
        meeting.lines.append(ln)
    return meeting
