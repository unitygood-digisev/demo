"""共用輸出版型：.xlsx、.docx、.md。

每份輸出都帶頁尾：資料截至日期、輸入檔名、執行編號、資料等級、待補清單，
可另附「計算方法」段。表格中的空值一律顯示「待補」。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from docx import Document
from docx.shared import Cm, Pt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from shared.classify import Classifier
from shared.dates import MISSING, fmt_date

LEVEL_BANNER = {
    "公開": "資料等級：公開",
    "內部一般": "資料等級：內部一般",
    "內部敏感": "內部敏感：僅執行長與主管",
    "客戶機密": "客戶機密：僅執行長與主管",
}
_SHEET_NAME_MAX = 31


_FIXED_TIME = "2000-01-01T00:00:00Z"
_CORE_TIME = re.compile(
    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)


def _make_reproducible(path: Path) -> None:
    """固定 Office 檔內的時間戳，讓同樣內容產生完全相同的檔案。"""
    with zipfile.ZipFile(path) as zin:
        entries = [(i.filename, zin.read(i.filename)) for i in zin.infolist()]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries:
            if name == "docProps/core.xml":
                data = _CORE_TIME.sub(rb"\g<1>" + _FIXED_TIME.encode() + rb"\g<2>", data)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(info, data)
    tmp.replace(path)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]()#<>|!~])")


def md_escape(text: str) -> str:
    """跳脫 markdown 符號，避免文字變成連結、標題或表格；換行壓成空白。"""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(str(text).split()))


def make_run_id(system: str, as_of: dt.date, input_files: list[Path]) -> str:
    """執行編號＝系統-日期-輸入檔內容雜湊前 8 碼。同樣輸入得到同樣編號。"""
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in input_files):
        h.update(p.name.encode("utf-8"))
        h.update(Path(p).read_bytes() if Path(p).exists() else b"<missing>")
    return f"{system}-{as_of.strftime('%Y%m%d')}-{h.hexdigest()[:8]}"


@dataclass
class Footer:
    as_of: dt.date
    input_files: list[str]
    run_id: str
    level: str
    missing: list[str] = field(default_factory=list)  # 待補清單
    method: list[str] = field(default_factory=list)  # 計算方法

    def __post_init__(self) -> None:
        # 不認得或沒給的等級，一律當作客戶機密標示
        self.level = Classifier().normalize(self.level)

    def lines(self) -> list[str]:
        out = [
            f"資料截至：{fmt_date(self.as_of)}",
            f"輸入檔：{'、'.join(self.input_files) if self.input_files else '無'}",
            f"執行編號：{self.run_id}",
            f"資料等級：{self.level}",
            "待補清單：" + ("無" if not self.missing else ""),
        ]
        out += [f"  - {m}" for m in self.missing]
        if self.method:
            out.append("計算方法：")
            out += [f"  - {m}" for m in self.method]
        return out


@dataclass
class Section:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    table: pd.DataFrame | None = None


def fill_missing(df: pd.DataFrame) -> pd.DataFrame:
    """空值、空字串一律顯示「待補」；日期轉成 YYYY-MM-DD。"""
    out = df.copy().astype(object)
    for col in out.columns:
        out[col] = [_cell(v) for v in out[col]]
    return out


def _cell(v: object) -> object:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return MISSING
    if isinstance(v, str) and not v.strip():
        return MISSING
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _append(ws, values: list) -> None:
    """寫入一列；以「=」開頭的文字維持為文字，不變成 Excel 公式。"""
    ws.append(values)
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"


LIGHT_FILL = {"紅": "F8CBAD", "黃": "FFE699", "綠": "C6E0B4"}


def _color_lights(sh, header_row: int, df: pd.DataFrame) -> None:
    """「燈號」欄依紅／黃／綠上色。"""
    if "燈號" not in df.columns:
        return
    col = list(df.columns).index("燈號") + 1
    for r in range(header_row + 1, header_row + 1 + len(df)):
        cell = sh.cell(row=r, column=col)
        color = LIGHT_FILL.get(str(cell.value))
        if color:
            cell.fill = PatternFill("solid", fgColor=color)


def write_xlsx(
    path: Path,
    headline: str,
    sheets: dict[str, pd.DataFrame],
    footer: Footer,
    overview: pd.DataFrame | None = None,
) -> Path:
    """第一個分頁放等級標籤、結論（可多行，以換行分隔）、總覽表、頁尾；之後每個分頁一張表。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "總覽"
    ws.append([LEVEL_BANNER.get(footer.level, footer.level)])
    ws["A1"].font = Font(bold=True, color="C00000")
    for i, line in enumerate(headline.splitlines() or [headline]):
        _append(ws, [line])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=13 if i == 0 else 11)
    ws.append([])
    if overview is not None:
        ov = fill_missing(overview)
        ws.append([str(c) for c in ov.columns])
        hdr = ws.max_row
        for c in range(1, len(ov.columns) + 1):
            ws.cell(row=hdr, column=c).font = Font(bold=True)
            ws.cell(row=hdr, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
        for row in ov.itertuples(index=False):
            _append(ws, list(row))
        _color_lights(ws, hdr, ov)
        ws.append([])
    for line in footer.lines():
        _append(ws, [line])
    for name, df in sheets.items():
        sh = wb.create_sheet(name[:_SHEET_NAME_MAX])
        sh.append([LEVEL_BANNER.get(footer.level, footer.level)])
        df = fill_missing(df)
        sh.append([str(c) for c in df.columns])
        for c in range(1, len(df.columns) + 1):
            sh.cell(row=2, column=c).font = Font(bold=True)
            sh.cell(row=2, column=c).fill = PatternFill("solid", fgColor="DDEBF7")
        for row in df.itertuples(index=False):
            _append(sh, list(row))
        _color_lights(sh, 2, df)
        sh.append([])
        for line in footer.lines():
            _append(sh, [line])
        for i, col in enumerate(df.columns, start=1):
            sh.column_dimensions[get_column_letter(i)].width = max(
                10, min(40, len(str(col)) * 2 + 4)
            )
    wb.properties.creator = "unity-mgmt-suite"
    wb.properties.created = dt.datetime(2000, 1, 1)  # 固定時間，讓重跑結果可比對
    wb.properties.modified = dt.datetime(2000, 1, 1)
    wb.save(path)
    _make_reproducible(path)
    return path


def write_docx(
    path: Path,
    title: str,
    headline: str,
    sections: list[Section],
    footer: Footer,
    compact: bool = False,
) -> Path:
    """compact=True：窄邊界、小字、段落不留空，用於要塞進一頁的報表（例如管理層週報）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    if compact:
        sec = doc.sections[0]
        sec.top_margin = sec.bottom_margin = Cm(1.5)
        sec.left_margin = sec.right_margin = Cm(1.8)
        for name in ("Normal", "Heading 1", "Heading 2", "Heading 3"):
            st = doc.styles[name]
            st.paragraph_format.space_before = Pt(4 if name != "Normal" else 0)
            st.paragraph_format.space_after = Pt(2)
        doc.styles["Normal"].font.size = Pt(9.5)
        doc.styles["Heading 1"].font.size = Pt(15)
        doc.styles["Heading 2"].font.size = Pt(11.5)
        doc.styles["Heading 3"].font.size = Pt(9)
    doc.sections[0].header.paragraphs[0].text = LEVEL_BANNER.get(footer.level, footer.level)
    doc.add_heading(title, level=1)
    doc.add_paragraph(headline).runs[0].bold = True
    for s in sections:
        doc.add_heading(s.title, level=2)
        for p in s.paragraphs:
            doc.add_paragraph(p)
        if s.table is not None:
            df = fill_missing(s.table)
            t = doc.add_table(rows=1, cols=len(df.columns))
            t.style = "Table Grid"
            for i, c in enumerate(df.columns):
                t.rows[0].cells[i].text = str(c)
            for row in df.itertuples(index=False):
                cells = t.add_row().cells
                for i, v in enumerate(row):
                    cells[i].text = str(v)
    doc.add_heading("頁尾資訊", level=3)
    for line in footer.lines():
        para = doc.add_paragraph(line)
        if compact:
            for run in para.runs:
                run.font.size = Pt(7.5)
    doc.core_properties.author = "unity-mgmt-suite"
    doc.core_properties.created = dt.datetime(2000, 1, 1)
    doc.core_properties.modified = dt.datetime(2000, 1, 1)
    doc.save(path)
    _make_reproducible(path)
    return path


def to_markdown(title: str, headline: str, sections: list[Section], footer: Footer) -> str:
    out = [
        f"> {LEVEL_BANNER.get(footer.level, footer.level)}",
        "",
        f"# {title}",
        "",
        f"**{headline}**",
        "",
    ]
    for s in sections:
        out += [f"## {s.title}", ""]
        out += [p + "\n" for p in s.paragraphs]
        if s.table is not None:
            df = fill_missing(s.table)
            out.append("| " + " | ".join(str(c) for c in df.columns) + " |")
            out.append("|" + "---|" * len(df.columns))
            for row in df.itertuples(index=False):
                cells = (str(v).replace("\\|", "／").replace("|", "／") for v in row)
                out.append("| " + " | ".join(cells) + " |")
            out.append("")
    out += ["---", ""] + [f"{line}  " for line in footer.lines()]
    return "\n".join(out) + "\n"


def write_md(
    path: Path, title: str, headline: str, sections: list[Section], footer: Footer
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_markdown(title, headline, sections, footer), encoding="utf-8")
    return path
