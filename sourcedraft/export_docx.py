"""Markdown draft -> Word (.docx), the format consultants hand around.

Review markers are made visible: 【待…】 gaps get a yellow highlight, [源自…]/[沿用…]/[依…計算]
anchors are small grey text so they read as annotations rather than prose.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

TOKEN = re.compile(r"(【[^】]*】|\[(?:源自|沿用|依)[^\]]*\]|\*\*[^*]+\*\*|`[^`]+`)")
FONT = "Microsoft JhengHei"


def _style_run(run, *, size: float | None = None) -> None:
    run.font.name = FONT
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    if size:
        run.font.size = Pt(size)


def _add_inline(par, text: str) -> None:
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith("【"):
            run = par.add_run(part)
            run.bold = True
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            _style_run(run)
        elif part.startswith("["):
            run = par.add_run(part)
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
            _style_run(run, size=8)
        elif part.startswith("**"):
            run = par.add_run(part[2:-2])
            run.bold = True
            _style_run(run)
        elif part.startswith("`"):
            run = par.add_run(part[1:-1])
            _style_run(run, size=9)
        else:
            _style_run(par.add_run(part))


def _is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|?[\s:\-|]+\|?", line.strip())) and "-" in line


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_docx(markdown: str, out_path: Path, title: str | None = None) -> Path:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    if title:
        doc.core_properties.title = title

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = min(len(heading.group(1)), 4)
            h = doc.add_heading(level=level)
            _add_inline(h, heading.group(2))
            i += 1
            continue
        if stripped in ("---", "***"):
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            header = _cells(stripped)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            table = doc.add_table(rows=1 + len(rows), cols=len(header))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for c, text in enumerate(header):
                cell = table.rows[0].cells[c]
                cell.text = ""
                _add_inline(cell.paragraphs[0], f"**{text}**" if text else "")
            for r, row in enumerate(rows, start=1):
                for c in range(len(header)):
                    cell = table.rows[r].cells[c]
                    cell.text = ""
                    _add_inline(cell.paragraphs[0], row[c] if c < len(row) else "")
            continue
        bullet = re.match(r"^([-*]|\d+[.、])\s+(.*)$", stripped)
        if bullet:
            style = "List Number" if bullet.group(1)[0].isdigit() else "List Bullet"
            _add_inline(doc.add_paragraph(style=style), bullet.group(2))
            i += 1
            continue
        if stripped.startswith(">"):
            p = doc.add_paragraph(style="Intense Quote")
            _add_inline(p, stripped.lstrip("> "))
            i += 1
            continue
        _add_inline(doc.add_paragraph(), stripped)
        i += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
