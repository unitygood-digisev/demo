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
FILE_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
TEXT_DATE = re.compile(r"會議日期[^：:]*[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

_FULL = re.compile(r"(\d{4})\s*[/年-]\s*(\d{1,2})\s*[/月-]\s*(\d{1,2})\s*日?")
_MD_CN = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_MD = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/])")
_APPROX = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(底|初|中旬|上旬|下旬|中)")
_MONTH = re.compile(r"(?<![\d/])(\d{1,2})\s*月(?!\s*\d)")
_YEAR_END = re.compile(r"年底")


@dataclass(frozen=True)
class Approx:
    label: str  # 例：2026年10月底
    end: dt.date  # 這段時間的最後一天，用來判斷是否在看板日期之後


@dataclass
class Line:
    no: int  # 第幾行（從 1 起算）
    text: str
    section: str = ""
    skipped: bool = False  # 財務、人事、行政段落
    heading: bool = False
    label: str = ""
    label_only: bool = False  # 「名稱：」後面沒有內容，底下的條目屬於這個名稱
    exact: list[dt.date] = field(default_factory=list)
    approx: list[Approx] = field(default_factory=list)
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
    skip_label_words: tuple[str, ...]
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
            skip_label_words=tuple(str(x) for x in c.get("skip_label_words") or ()),
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


def extract_dates(text: str, meeting_date: dt.date) -> tuple[list[dt.date], list[Approx]]:
    """找出一行裡的日期。年份＝會議那一年；這一行寫「明年」時加一年。不認得的寫法不猜。"""
    year = meeting_date.year + (1 if "明年" in text else 0)
    t = unicodedata.normalize("NFKC", text)
    exact: list[dt.date] = []
    approx: list[Approx] = []

    def take(pattern: re.Pattern, fn) -> None:
        nonlocal t
        out = []
        last = 0
        for m in pattern.finditer(t):
            fn(m)
            out.append(t[last : m.start()] + " " * (m.end() - m.start()))
            last = m.end()
        t = "".join(out) + t[last:]

    take(_FULL, lambda m: exact.append(_safe(*(int(x) for x in m.groups()))))
    take(_MD_CN, lambda m: exact.append(_safe(year, int(m[1]), int(m[2]))))
    take(_MD, lambda m: exact.append(_safe(year, int(m[1]), int(m[2]))))

    def add_approx(m: re.Match) -> None:
        mo = int(m[1])
        if 1 <= mo <= 12:
            last = calendar.monthrange(year, mo)[1]
            end = {"初": 10, "上旬": 10, "中": 20, "中旬": 20}.get(m[2], last)
            approx.append(Approx(f"{year}年{mo}月{m[2]}", dt.date(year, mo, end)))

    take(_APPROX, add_approx)

    def add_month(m: re.Match) -> None:
        mo = int(m[1])
        if 1 <= mo <= 12:
            last = calendar.monthrange(year, mo)[1]
            approx.append(Approx(f"{year}年{mo}月", dt.date(year, mo, last)))

    take(_MONTH, add_month)
    take(_YEAR_END, lambda m: approx.append(Approx(f"{year}年底", dt.date(year, 12, 31))))
    exact = sorted({d for d in exact if d is not None})
    return exact, approx


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


def _is_heading(s: str) -> bool:
    if not s or BULLET.match(s) and not NUMBERED_HEADING.match(s):
        return False
    if s.startswith("#") or NUMBERED_HEADING.match(s) or s.endswith(("：", ":")):
        return True
    return len(s) <= 20 and not re.search(r"[：:]", s) and not re.search(r"\d", s)


def parse_meeting(path: Path, rules: MeetingRules) -> Meeting:
    m = FILE_DATE.search(path.name)
    date = _safe(*(int(x) for x in m.groups())) if m else None
    if date is None:
        return Meeting(path, None, problem="檔名沒有日期（需要 8 碼，例如 20260907），未使用")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return Meeting(path, date, problem="不是 UTF-8 編碼，請用記事本另存為 UTF-8，未使用")
    meeting = Meeting(path, date)
    section, skipping = "", False
    for no, text in enumerate(raw.splitlines(), start=1):
        s = text.strip()
        if not s:
            continue
        td = TEXT_DATE.search(s)
        if td and meeting.text_date is None:
            meeting.text_date = _safe(*(int(x) for x in td.groups()))
        ln = Line(no, s)
        if _is_heading(s):
            ln.heading = True
            section = s.lstrip("#").rstrip("：:").strip()
            skipping = any(w in section for w in rules.skip_section_words)
        ln.section, ln.skipped = section, skipping
        body = BULLET.sub("", s, count=1).lstrip("#").strip()
        lm = LABEL.match(body)
        if lm and not ln.heading:
            label = lm[1].strip()
            if any(w in label for w in rules.skip_label_words):
                ln.skipped = True
            elif not re.fullmatch(r"[\d/\s～~\-、]+", label) and not re.search(r"[，。,]", label):
                ln.label = label
                ln.label_only = not lm[2].strip()
        if not ln.skipped:
            ln.exact, ln.approx = extract_dates(s, date)
            ln.stage_words = [w for w in rules.stage_words if w in s]
            # 長的字眼已涵蓋短的（例如「已結案」含「結案」），只留長的
            ln.stage_words = [
                w for w in ln.stage_words if not any(w != o and w in o for o in ln.stage_words)
            ]
        meeting.lines.append(ln)
    return meeting
