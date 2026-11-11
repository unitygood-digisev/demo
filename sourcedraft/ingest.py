"""Turn client material (docx / xlsx / pdf / md / txt) into anchored plain text.

Anchors such as 〔表3〕, 〔工作表 人力 · 第12列〕 or 〔第4頁〕 are kept in the text
so the model can cite a locatable source in its [源自…] markers.
Client originals are only read, never modified (handbook rule: 客戶原始資料不覆蓋).
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED = {".docx", ".xlsx", ".xlsm", ".pdf", ".md", ".txt", ".csv"}


def load_many(paths: list[Path]) -> str:
    parts = []
    for p in paths:
        parts.append(f"=== 檔案：{p.name} ===\n{load(p)}")
    return "\n\n".join(parts)


def load(path: Path) -> str:
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"不支援的檔案格式：{path.name}（支援 {', '.join(sorted(SUPPORTED))}）")
    if ext == ".docx":
        return _docx(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(path)
    if ext == ".pdf":
        return _pdf(path)
    return path.read_text(encoding="utf-8-sig")


def _cell_text(text: str) -> str:
    return " ".join(text.split()).replace("|", "｜")


def _docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    out: list[str] = []
    table_no = 0
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            if style.startswith("heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                out.append("#" * min(int(level) + 1, 6) + " " + text)
            else:
                out.append(text)
        elif tag == "tbl":
            table_no += 1
            out.append(f"〔表{table_no}〕")
            out.append(_table_md(Table(child, doc)))
    return "\n\n".join(out)


def _table_md(table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        prev_tc = None
        for cell in row.cells:
            if cell._tc is prev_tc:  # horizontally merged cell repeats
                continue
            prev_tc = cell._tc
            cells.append(_cell_text(cell.text))
        if rows and cells == rows[-1]:  # vertically merged cells repeat the whole row
            continue
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _xlsx(path: Path) -> str:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    wb = load_workbook(str(path), data_only=True, read_only=True)
    out: list[str] = []
    for ws in wb.worksheets:
        rows = []
        max_col = 0
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            vals = ["" if v is None else _cell_text(str(v)) for v in row]
            while vals and vals[-1] == "":
                vals.pop()
            if not any(vals):
                continue
            max_col = max(max_col, len(vals))
            rows.append((r_idx, vals))
        if not rows:
            continue
        out.append(f"〔工作表 {ws.title}〕")
        header = "| 列 | " + " | ".join(get_column_letter(i) for i in range(1, max_col + 1)) + " |"
        lines = [header, "|" + " --- |" * (max_col + 1)]
        for r_idx, vals in rows:
            vals = vals + [""] * (max_col - len(vals))
            lines.append(f"| {r_idx} | " + " | ".join(vals) + " |")
        out.append("\n".join(lines))
    wb.close()
    return "\n\n".join(out)


def _pdf(path: Path) -> str:
    import pdfplumber

    out: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                out.append(f"〔第{i}頁〕\n{text}")
    return "\n\n".join(out)
