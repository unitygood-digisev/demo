"""Client supplementary-data checklist (客戶補件清單) built from the internal drafts' appendices.

Every appendix row gets an ID (CH4-12). The model rewrites the rows the client must act on into
client-facing items grouped by department, and lists the consultant-only rows separately with a
reason. The program then checks that every row ID is accounted for exactly once, so nothing is
dropped silently, and that no internal wording leaks into the client text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .verify import _appendix_rows, split_appendix

PRIORITIES = ["必要", "建議"]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items", "consultant_only"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["department", "chapter", "section", "request", "format", "priority", "source_ids"],
                "properties": {
                    "department": {"type": "string"},
                    "chapter": {"type": "string"},
                    "section": {"type": "string"},
                    "request": {"type": "string"},
                    "format": {"type": "string"},
                    "priority": {"type": "string", "enum": PRIORITIES},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "consultant_only": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id", "reason"],
                "properties": {"source_id": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
    },
}

# Internal vocabulary that must not reach the client.
INTERNAL = re.compile(r"\[源自|\[沿用|\[依[^\]]*計算|待顧問|顧問複核|事實表|程式檢核|Step ?\d|旗標|F\d+|C\d+(?!\w)|internal")


@dataclass
class Row:
    id: str
    chapter: str
    section: str
    status: str
    content: str
    note: str


@dataclass
class Checklist:
    client: str
    year: str
    items: list[dict[str, Any]]
    consultant_only: list[dict[str, Any]]
    rows: list[Row]
    problems: list[str] = field(default_factory=list)


def collect_rows(chapters: list[tuple[str, Path]]) -> list[Row]:
    """chapters: (short chapter label such as 'CH4', internal draft markdown path)."""
    rows: list[Row] = []
    for label, path in chapters:
        _, appendix = split_appendix(path.read_text(encoding="utf-8"))
        for n, cells in enumerate(_appendix_rows(appendix), start=1):
            cells = (cells + [""] * 5)[:5]
            rows.append(Row(f"{label}-{n}", label, cells[1], cells[2], cells[3], cells[4]))
    return rows


def build_prompt(client: str, year: str, rows: list[Row], departments: dict[str, str]) -> tuple[str, str]:
    system = resources.files("sourcedraft").joinpath("prompts", "checklist.md").read_text(encoding="utf-8")
    dept = "\n".join(f"- {ch}：{d}" for ch, d in departments.items()) or "（未提供）"
    table = "\n".join(f"| {r.id} | {r.section} | {r.status} | {r.content} | {r.note} |" for r in rows)
    user = (f"客戶：{client}\n報導年度：{year}\n\n各章資料蒐集表標示的建議填表部室：\n{dept}\n\n"
            f"顧問版附錄（共 {len(rows)} 列）：\n\n| ID | 對應小節 | 狀態 | 需核對／補件內容 | 風險提示／查證備忘 |\n"
            f"| --- | --- | --- | --- | --- |\n{table}\n\n請輸出 JSON。")
    return system, user


def validate(cl: Checklist) -> list[str]:
    problems: list[str] = []
    ids = [r.id for r in cl.rows]
    seen: dict[str, int] = {}
    for it in cl.items:
        for sid in it["source_ids"]:
            seen[sid] = seen.get(sid, 0) + 1
    for c in cl.consultant_only:
        seen[c["source_id"]] = seen.get(c["source_id"], 0) + 1
    missing = [i for i in ids if i not in seen]
    unknown = [i for i in seen if i not in ids]
    if missing:
        problems.append(f"附錄列未處理（未列入補件清單，也未說明為顧問自行處理）：{'、'.join(missing)}")
    if unknown:
        problems.append(f"清單引用了不存在的附錄列：{'、'.join(unknown)}")
    for it in cl.items:
        for key in ("request", "format", "section"):
            if INTERNAL.search(it[key]):
                problems.append(f"客戶版文字含內部用語：{it[key][:60]}")
        if not it["source_ids"]:
            problems.append(f"補件項目沒有對應的附錄列：{it['request'][:60]}")
    return problems


def run(client: str, year: str, chapters: list[tuple[str, Path]], departments: dict[str, str], llm) -> Checklist:
    rows = collect_rows(chapters)
    system, user = build_prompt(client, year, rows, departments)
    data = llm.extract(system, user, SCHEMA)
    cl = Checklist(client, year, data["items"], data["consultant_only"], rows)
    cl.problems = validate(cl)
    return cl


def chapter_rank(chapter: str) -> tuple[int, str]:
    """序論 first, then CH1…CH6; 「CH1／CH5」 sorts by its first chapter."""
    first = re.split(r"[／/、]", chapter)[0].strip()
    if first.startswith("序論"):
        return (0, chapter)
    m = re.search(r"\d+", first)
    return (int(m.group(0)) + 1 if m else 99, chapter)


def to_json(cl: Checklist) -> dict[str, Any]:
    return {"client": cl.client, "year": cl.year, "items": cl.items, "consultant_only": cl.consultant_only,
            "rows": [r.__dict__ for r in cl.rows], "problems": cl.problems}


def from_json(data: dict[str, Any]) -> Checklist:
    return Checklist(data["client"], data["year"], data["items"], data["consultant_only"],
                     [Row(**r) for r in data["rows"]], data.get("problems", []))


def _grouped(cl: Checklist) -> list[tuple[str, list[dict[str, Any]]]]:
    order: list[str] = []
    for it in cl.items:
        if it["department"] not in order:
            order.append(it["department"])
    return [(d, sorted([i for i in cl.items if i["department"] == d],
                       key=lambda i: (PRIORITIES.index(i["priority"]), chapter_rank(i["chapter"]), i["section"])))
            for d in order]


def to_markdown(cl: Checklist, due: str = "") -> str:
    must = sum(i["priority"] == "必要" for i in cl.items)
    lines = [f"# {cl.client} {cl.year} 年永續報告書　補件清單", "",
             f"感謝貴院協助提供資料。初稿彙整後，尚有以下 {len(cl.items)} 項資料需請各單位補充或確認，"
             f"其中 {must} 項為永續報告書必要揭露項目。",
             "",
             f"- 報導期間：{cl.year}/1/1–{cl.year}/12/31，所有數據請以此期間為準。",
             "- 「必要」為準則要求揭露的項目，缺少時須在報告書中說明省略原因；「建議」可提升報告書完整度。",
             "- 數據請盡量提供原始統計檔（Excel 或系統匯出檔），並註明統計截止日與計算方式。"]
    if due:
        lines.append(f"- 請於 {due} 前回覆。")
    n = 0
    for dept, items in _grouped(cl):
        lines += ["", f"## {dept}（{len(items)} 項）", "", "| 序號 | 章節 | 需提供資料 | 建議格式 | 類別 |", "| :--- | :--- | :--- | :--- | :---: |"]
        for it in items:
            n += 1
            sec = f"{it['chapter']} {it['section']}".strip()
            lines.append(f"| {n} | {sec} | {it['request']} | {it['format']} | {it['priority']} |")
    return "\n".join(lines) + "\n"


def to_xlsx(cl: Checklist, path: Path) -> Path:
    """Internal tracking copy (handbook 04-5: 缺口清單 with 催收紀錄)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "補件追蹤"
    head = ["序號", "建議提供單位", "章節", "小節", "需提供資料", "建議格式", "類別", "對應顧問版附錄",
            "第一次催收", "第二次催收", "回覆日期", "狀態", "備註"]
    ws.append(head)
    n = 0
    for dept, items in _grouped(cl):
        for it in items:
            n += 1
            ws.append([n, dept, it["chapter"], it["section"], it["request"], it["format"], it["priority"],
                       "、".join(it["source_ids"]), None, None, None, "未回覆", None])
    fill = PatternFill("solid", fgColor="1F3864")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    for col, width in zip("ABCDEFGHIJKLM", [6, 14, 8, 18, 50, 36, 8, 16, 12, 12, 12, 10, 24]):
        ws.column_dimensions[col].width = width
    for col in "IJK":
        for c in ws[col][1:]:
            c.number_format = "yyyy-mm-dd"
    dv = DataValidation(type="list", formula1='"未回覆,部分回覆,已回覆,不提供（說明省略原因）"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"L2:L{max(2, n + 1)}")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:M{n + 1}"

    ex = wb.create_sheet("顧問自行處理")
    ex.append(["顧問版附錄", "原內容", "不列入補件清單的原因"])
    by_id = {r.id: r for r in cl.rows}
    for c in cl.consultant_only:
        r = by_id.get(c["source_id"])
        ex.append([c["source_id"], r.content if r else "", c["reason"]])
    for cell in ex[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
    for col, width in zip("ABC", [14, 70, 50]):
        ex.column_dimensions[col].width = width
    for row in ex.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path
