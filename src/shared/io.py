"""讀取 Excel/CSV，依欄位定義檢查，所有錯誤一次列出。

- 原始檔只讀不寫。
- 欄位名稱不同時，用 column_map（設定檔提供）改名，不動原檔。
- 錯誤清單每筆含：檔名、Excel 列號（標題列＝第 1 列）、欄位、問題、原始值。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from shared.dates import DateParseError, parse_date

ColumnType = Literal["text", "int", "amount", "date", "enum"]
HEADER_ROW = 1  # Excel 第 1 列是標題，資料從第 2 列開始


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: ColumnType = "text"
    required: bool = True
    allowed: tuple[str, ...] = ()
    label: str = ""  # 繁體中文說明，出現在錯誤訊息


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[ColumnSpec, ...]
    unique_key: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    file: str
    row: int | None  # Excel 列號；整個檔案或整欄的問題為 None
    column: str | None
    problem: str
    value: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "檔案": self.file,
            "列號": self.row if self.row is not None else "（整份）",
            "欄位": self.column or "（整份）",
            "問題": self.problem,
            "原始值": self.value,
        }


@dataclass
class LoadResult:
    data: pd.DataFrame
    issues: list[ValidationIssue] = field(default_factory=list)
    bad_rows: set[int] = field(default_factory=set)  # 有錯誤的 Excel 列號

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def clean(self) -> pd.DataFrame:
        """去掉有錯誤的列之後的資料。"""
        return self.data[~self.data["_row"].isin(self.bad_rows)]


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    if v is pd.NaT:
        return True
    return isinstance(v, str) and not v.strip()


def _convert(v: Any, col: ColumnSpec) -> Any:
    """轉型失敗丟 ValueError（訊息為繁中）。"""
    if col.type == "text":
        return str(v).strip()
    if col.type == "enum":
        s = str(v).strip()
        if col.allowed and s not in col.allowed:
            raise ValueError(f"不在允許值內（允許：{'、'.join(col.allowed)}）")
        return s
    if col.type == "date":
        try:
            return parse_date(v if not isinstance(v, pd.Timestamp) else v.to_pydatetime())
        except DateParseError as e:
            raise ValueError("日期錯誤（應為 YYYY-MM-DD 的有效日期）") from e
    if col.type in ("int", "amount"):
        if isinstance(v, bool):
            raise ValueError("不是數字")
        if isinstance(v, (int, float)):
            num = float(v)
        else:
            s = str(v).strip().replace(",", "")
            try:
                num = float(s)
            except ValueError as e:
                raise ValueError("不是數字") from e
        if col.type == "int":
            if not num.is_integer():
                raise ValueError("應為整數")
            return int(num)
        return num
    raise ValueError(f"未知的欄位型別 {col.type}")


def _read_raw(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return pd.read_excel(path, dtype=object, engine="openpyxl")
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    raise ValueError(f"不支援的檔案格式：{path.name}（只接受 .xlsx、.csv）")


def load_table(
    path: str | Path,
    spec: TableSpec,
    column_map: dict[str, str] | None = None,
) -> LoadResult:
    """讀檔並檢查。不會因為資料錯誤而中斷；錯誤都放在 issues。"""
    path = Path(path)
    fname = path.name
    issues: list[ValidationIssue] = []
    if not path.exists():
        issues.append(ValidationIssue(fname, None, None, "找不到檔案"))
        return LoadResult(pd.DataFrame(columns=["_row"]), issues)
    try:
        raw = _read_raw(path)
    except Exception as e:  # 讀檔失敗也要大聲列出，不要讓整個流程崩潰
        issues.append(ValidationIssue(fname, None, None, f"無法讀取檔案：{e}"))
        return LoadResult(pd.DataFrame(columns=["_row"]), issues)

    raw.columns = [str(c).strip() for c in raw.columns]
    if column_map:
        raw = raw.rename(columns=column_map)

    # 1. 欄位檢查（缺必填欄一次列完；選填欄缺少不算錯，值視為待補）
    for c in spec.columns:
        if c.required and c.name not in raw.columns:
            issues.append(ValidationIssue(fname, None, c.name, "缺少欄位（必填）"))
    present = [c for c in spec.columns if c.name in raw.columns]

    # 2. 逐列逐格檢查
    records: list[dict[str, Any]] = []
    bad_rows: set[int] = set()
    for i, row in enumerate(raw.to_dict("records")):
        excel_row = i + HEADER_ROW + 1
        if all(_is_blank(v) for v in row.values()):
            continue  # 全空白列略過（Excel 常見）
        rec: dict[str, Any] = {"_row": excel_row}
        for c in spec.columns:
            if c not in present:
                rec[c.name] = None
                if c.required:
                    bad_rows.add(excel_row)
                continue
            v = row.get(c.name)
            if _is_blank(v):
                rec[c.name] = None
                if c.required:
                    issues.append(ValidationIssue(fname, excel_row, c.name, "必填欄位空白"))
                    bad_rows.add(excel_row)
                continue
            try:
                rec[c.name] = _convert(v, c)
            except ValueError as e:
                rec[c.name] = None
                issues.append(ValidationIssue(fname, excel_row, c.name, str(e), _show(v)))
                bad_rows.add(excel_row)
        records.append(rec)

    data = pd.DataFrame(records, columns=["_row"] + [c.name for c in spec.columns])

    # 3. 重複鍵
    if spec.unique_key and spec.unique_key in raw.columns and not data.empty:
        keys = data[spec.unique_key]
        dup_mask = keys.notna() & keys.duplicated(keep=False)
        for _, r in data[dup_mask].iterrows():
            issues.append(
                ValidationIssue(
                    fname, int(r["_row"]), spec.unique_key, "重複的 ID", _show(r[spec.unique_key])
                )
            )
            bad_rows.add(int(r["_row"]))

    issues.sort(key=lambda x: (x.row is not None, x.row or 0, x.column or ""))
    return LoadResult(data, issues, bad_rows)


def _show(v: Any) -> str:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def issues_frame(issues: list[ValidationIssue]) -> pd.DataFrame:
    """把錯誤清單轉成表格，供「資料品質」分頁使用。"""
    cols = ["檔案", "列號", "欄位", "問題", "原始值"]
    return pd.DataFrame([i.as_dict() for i in issues], columns=cols)
