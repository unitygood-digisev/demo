"""Project catalog: index the SOP folder tree so drafting inputs can be found by client and year.

Input is a flat Drive listing (id, title, mimeType, parentId, modifiedTime, owner, viewUrl, fileSize)
plus the IDs of the client root folders. Each file is classified by:

  stage  作業手冊階段（00 商務 … 09 結案），from its title first, then the nearest folder name
  role   溯稿用途：往年完稿／自收表／查證意見／高層訪談／重大主題／同業參考／其他
  year   年度標記 found in the title or path (民國年 converted to 西元)

Classification is keyword based and deliberately conservative: it suggests, and the consultant
corrects the sheet by hand. `suggest()` then proposes inputs for a draft run.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

FOLDER = "application/vnd.google-apps.folder"

# Most specific first: a file titled 「查證意見回覆」 inside 「05 草稿」 is 確信, not 撰稿.
STAGE_RULES: list[tuple[str, str]] = [
    ("07 確信", r"查證|確信|稽核|OFI|查驗證|書審|BSI|SGS|DNV|貝爾|意見與建議|PBC|聲明書"),
    ("09 結案", r"結案|發證|最終版|定稿|final|FINAL|Final|申報|上架|KM沉澱"),
    ("06 美編", r"美編|主視覺|版型|排版"),
    ("02 重大主題", r"重大|問卷|衝擊鑑別|利害關係人|矩陣"),
    ("03 策略藍圖", r"策略藍圖|工作坊|便利貼|願景|海報"),
    ("04 資蒐", r"資蒐|資料蒐集|資料搜集|資料收集|填表|佐證|資蒐會議"),
    ("05 撰稿", r"草稿|初稿|撰稿|文稿|校稿|翻譯|追蹤修訂|GRI對照|GRI頁碼|內容索引|SASB對照|章節架構|_V\d|V\d+\b"),
    ("01 啟動", r"啟動|啟始|kick|Kick|高層訪談|訪綱|總控|議程|教育訓練|組織圖"),
    ("00 商務", r"合約|報價|請款|發票|公文|需求調查|補助|核定"),
]

DOC_EXT = {"docx", "doc", "pdf"}
SURVEY_EXT = {"docx", "doc", "xlsx", "xls", "pdf"}
FINAL_WORDS = re.compile(r"最終版|定稿|final|終版|完稿", re.I)
NOT_REPORT = re.compile(r"意見|對照|索引|頁碼|自評|清單|鉤稽|回覆|說明|議程|簡報|美編修正|差異|會議|範例|指南|手冊|目標|計畫|總控|樣板|模板")
SURVEY_WORDS = re.compile(r"資蒐表|資料蒐集表|資料搜集表|資料收集表|蒐集表")


@dataclass
class Entry:
    client: str
    path: str
    title: str
    kind: str
    stage: str
    role: str
    year: str
    modified: str
    owner: str
    size: str
    url: str
    file_id: str


def detect_year(text: str, *, weak: bool = True) -> str:
    """Western year 2018–2035, or 民國 107–124 written with 年 (a range 「114~118年」 takes its first year).
    With weak=True a 7-digit 民國 date such as 1150828 also counts; it is usually a publication date,
    so callers prefer explicit years in the title and the folder path first."""
    m = re.search(r"(?<!\d)(20(?:1[89]|2\d|3[0-5]))(?!\d)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?<!\d)(1(?:0[7-9]|1\d|2[0-4]))(?:\s*[~～至-]\s*1\d\d)?年", text)
    if m:
        return str(int(m.group(1)) + 1911)
    if weak:
        m = re.search(r"(?<!\d)(1(?:0[7-9]|1\d|2[0-4]))(?=\d{4}(?!\d))", text)
        if m:
            return str(int(m.group(1)) + 1911)
    return ""


def classify_stage(title: str, folders: list[str]) -> str:
    for text in [title, *reversed(folders)]:  # the file's own name, then its nearest folder upward
        for stage, pattern in STAGE_RULES:
            if re.search(pattern, text):
                return stage
    return ""


FULL_REPORT = re.compile(r"永續報告書|ESG全文|ESG報告書|CSR報告書|Sustainability Report", re.I)
DRAFT_MARK = re.compile(r"修|草稿|初稿|整合|S2後|追蹤|第.章|乾淨版|翻譯|第.版")
PEER = re.compile(r"參考|其他醫院|同業|範例")


def classify_role(title: str, ext: str, stage: str, path: str) -> str:
    if ext in SURVEY_EXT and SURVEY_WORDS.search(title):
        return "自收表"
    if ext in DOC_EXT and PEER.search(path):
        return "同業參考"
    if ext in DOC_EXT and not NOT_REPORT.search(title):
        named_final = FINAL_WORDS.search(title) or FINAL_WORDS.search(path)
        if named_final and re.search(r"報告書|永續|ESG|Sustainability|Report|final", title + path, re.I):
            return "往年完稿"
        # a whole-report file (「2025嘉義基督教醫院永續報告書.docx」「1150825-嘉基ESG全文V6.pdf」); the newest wins in suggest()
        if FULL_REPORT.search(title) and not DRAFT_MARK.search(title) and stage != "07 確信":
            return "往年完稿"
    if stage == "07 確信":
        return "查證意見"
    if re.search(r"訪談|訪綱", title + path):
        return "高層訪談"
    if stage == "02 重大主題":
        return "重大主題"
    return "其他"


def _ext(item: dict[str, Any]) -> str:
    ext = (item.get("fileExtension") or "").lower()
    if not ext and "." in item.get("title", ""):
        ext = item["title"].rsplit(".", 1)[-1].lower()
    if item.get("mimeType", "").startswith("application/vnd.google-apps."):
        ext = item["mimeType"].rsplit(".", 1)[-1]  # document / spreadsheet / presentation
    return ext


def build(items: Iterable[dict[str, Any]], roots: dict[str, str]) -> list[Entry]:
    """items: Drive listing (deduplicated by id). roots: root folder id -> client name."""
    by_id: dict[str, dict[str, Any]] = {}
    for it in items:
        if it.get("trashed"):
            continue
        by_id.setdefault(it["id"], it)

    def lineage(item: dict[str, Any]) -> tuple[str, list[str]] | None:
        folders: list[str] = []
        parent = item.get("parentId")
        seen = set()
        while parent and parent not in roots:
            if parent in seen or parent not in by_id:
                return None  # outside the indexed tree
            seen.add(parent)
            folders.append(by_id[parent]["title"])
            parent = by_id[parent].get("parentId")
        if not parent:
            return None
        return roots[parent], list(reversed(folders))

    entries: list[Entry] = []
    for it in by_id.values():
        if it.get("mimeType") == FOLDER or it["title"].startswith((".DS_Store", "~$")) or it["title"] in (".gitignore",):
            continue
        found = lineage(it)
        if found is None:
            continue
        client, folders = found
        if ".git" in folders:
            continue
        path = "／".join(folders)
        ext = _ext(it)
        stage = classify_stage(it["title"], folders)
        entries.append(Entry(
            client=client, path=path, title=it["title"], kind=ext, stage=stage,
            role=classify_role(it["title"], ext, stage, path),
            year=detect_year(it["title"], weak=False) or detect_year(path, weak=False) or detect_year(it["title"]),
            modified=(it.get("modifiedTime") or "")[:10], owner=it.get("owner", ""),
            size=str(it.get("fileSize", "")), url=it.get("viewUrl", ""), file_id=it["id"]))
    entries.sort(key=lambda e: (e.client, e.path, e.title))
    return entries


def summarize(entries: list[Entry]) -> list[dict[str, Any]]:
    """One row per client: what the drafting pipeline can use."""
    out = []
    for client in sorted({e.client for e in entries}):
        es = [e for e in entries if e.client == client]
        years = sorted({e.year for e in es if e.year})
        out.append({
            "client": client,
            "files": len(es),
            "years": "、".join(years),
            "往年完稿": sum(e.role == "往年完稿" for e in es),
            "自收表": sum(e.role == "自收表" for e in es),
            "查證意見": sum(e.role == "查證意見" for e in es),
            "高層訪談": sum(e.role == "高層訪談" for e in es),
            "未分類階段": sum(not e.stage for e in es),
            "last_modified": max((e.modified for e in es), default=""),
        })
    return out


def suggest(entries: list[Entry], client: str, year: str) -> dict[str, list[Entry]]:
    """Candidate inputs for drafting `client`'s report for reporting year `year`."""
    es = [e for e in entries if e.client == client]
    prev = str(int(year) - 1) if year.isdigit() else ""

    def ranked(xs: list[Entry]) -> list[Entry]:
        # a name that says 定稿／final／終版 beats a plain full-report name; then newest first;
        # Chinese editions first: drafting is in Chinese
        return sorted(xs, key=lambda e: (not re.search(r"_EN|英文|\bEN\b", e.title),
                                         bool(FINAL_WORDS.search(e.title)), e.modified), reverse=True)

    return {
        "往年完稿": ranked([e for e in es if e.role == "往年完稿" and (e.year == prev or not e.year)]),
        "自收表": ranked([e for e in es if e.role == "自收表" and e.year in (year, "")]),
        "查證意見": ranked([e for e in es if e.role == "查證意見" and e.year in (prev, "")]),
    }


COLUMNS = [f.name for f in fields(Entry)]
HEADERS = ["客戶", "資料夾路徑", "檔名", "類型", "作業手冊階段", "溯稿用途", "年度標記", "最後修改", "擁有者",
           "大小(bytes)", "連結", "檔案ID"]


def write_csv(entries: list[Entry], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for e in entries:
            w.writerow([getattr(e, c) for c in COLUMNS])


def read_csv(path: Path) -> list[Entry]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return [Entry(**dict(zip(COLUMNS, r))) for r in rows[1:] if r]


def as_dicts(entries: list[Entry]) -> list[dict[str, Any]]:
    return [asdict(e) for e in entries]
