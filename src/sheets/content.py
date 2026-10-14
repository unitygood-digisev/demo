"""從本機已產生的報表組出各分頁內容（不重新計算）。"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from shared.dates import DateParseError, parse_date

MISSING = "待補"
INTEL_COLUMNS = [
    "首次看到",
    "來源",
    "標題",
    "連結",
    "分類",
    "是否相關",
    "摘要",
    "對優樂地的意義",
    "分數",
]
INTEL_REQUIRED = ("標題", "連結")
SYSTEM_MARK = "資料等級："  # 系統寫的分頁，第 1 列第 1 格一定以此開頭
HISTORY_MARK = "週報日期"
DIGEST_KEYS = {
    "as_of": str,
    "title": str,
    "level": str,
    "level_banner": str,
    "run_id": str,
    "sentences": list,
    "metrics": list,
    "decisions": list,
    "decisions_more": int,
    "intel": list,
    "data_quality": list,
    "data_quality_more": int,
    "footer": list,
}


class SyncError(Exception):
    """同步無法進行（訊息為白話中文）。"""


@dataclass
class Tab:
    title: str
    rows: list[list]  # 第 1 列：等級與資料截至；之後是表格
    notes: list[str] = field(default_factory=list)  # 要大聲提示的事


def _cell(v: object) -> object:
    if v is None or (isinstance(v, str) and not v.strip()):
        return MISSING
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    return v


def read_sheet_table(
    path: Path, sheet: str, required: tuple[str, ...] = ()
) -> tuple[list[str], list[list]]:
    """讀本系統產生的 xlsx 分頁：表頭＝第 2 列，資料到第一個整列空白為止。"""
    try:
        wb = load_workbook(path, read_only=True)
    except Exception as e:  # 壞檔、空檔、不是 xlsx
        raise SyncError(f"{path.name} 已損壞或不是 Excel 檔，無法讀取") from e
    if sheet not in wb.sheetnames:
        raise SyncError(f"{path.name} 沒有「{sheet}」分頁")
    rows = list(wb[sheet].iter_rows(values_only=True))
    if len(rows) < 2 or not rows[1] or not any(rows[1]):
        raise SyncError(f"{path.name} 的「{sheet}」分頁找不到表頭（第 2 列）")
    header = [str(c).strip() if c is not None else "" for c in rows[1]]
    lost = [c for c in required if c not in header]
    if lost:
        raise SyncError(f"{path.name} 的「{sheet}」分頁缺少欄位：{'、'.join(lost)}")
    data = []
    for r in rows[2:]:
        if not r or all(c is None for c in r):
            break
        data.append([_cell(c) for c in r[: len(header)]])
    return header, data


def load_digest(digest_dir: Path, as_of: dt.date) -> dict:
    p = digest_dir / f"管理層週報_資料_{as_of.strftime('%Y%m%d')}.json"
    if not p.exists():
        raise SyncError(f"找不到 {as_of.isoformat()} 的週報資料檔，請先產生週報再同步")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        raise SyncError(f"週報資料檔 {p.name} 無法讀取，請重新產生週報") from e
    if not isinstance(d, dict):
        raise SyncError(f"週報資料檔 {p.name} 格式錯誤，請重新產生週報")
    bad = [
        k
        for k, t in DIGEST_KEYS.items()
        if not isinstance(d.get(k), t) or isinstance(d.get(k), bool)
    ]
    bad += (
        []
        if all(
            isinstance(m, dict) and {"label", "this", "prev", "change"} <= set(m)
            for m in d.get("metrics") or []
        )
        else ["metrics"]
    )
    if bad:
        raise SyncError(
            f"週報資料檔 {p.name} 缺少或寫錯欄位：{'、'.join(sorted(set(bad)))}，請重新產生週報"
        )
    return d


def _banner(d: dict) -> list:
    return [
        f"{d['level_banner'] if d['level_banner'].startswith(SYSTEM_MARK) else SYSTEM_MARK + d['level']}"
        f"｜資料截至 {d['as_of']}｜執行編號 {d['run_id']}"
    ]


def _system_note(digest: dict, key: str) -> str | None:
    """週報記錄該系統本週不是正常更新時，回傳原因。"""
    info = (digest.get("systems") or {}).get(key)
    if isinstance(info, dict) and info.get("status") not in (None, "ok"):
        return f"{info.get('name', key)}：{info.get('text', '本週未更新')}"
    return None


def build_tabs(
    names: dict[str, str], digest: dict, progress_xlsx: Path | None, intel_xlsx: Path | None
) -> list[Tab]:
    top = _banner(digest)
    tabs: list[Tab] = []

    rows: list[list] = [top, [digest["title"]], ["本週結論"]]
    rows += [[f"{i}. {s}"] for i, s in enumerate(digest["sentences"], 1)]
    rows += [[], ["關鍵指標", "本週", "上週", "變化", "單位"]]
    rows += [
        [m["label"], m["this"], m["prev"], m["change"], m.get("unit") or "—"]
        for m in digest["metrics"]
    ]
    rows += [[], ["需要您決定的事項"]] + (
        [[x] for x in digest["decisions"]] or [["本週沒有紅色預警。"]]
    )
    if digest["decisions_more"]:
        rows.append(
            [f"（其餘 {digest['decisions_more']} 條紅色預警，見「{names['alerts']}」分頁）"]
        )
    rows += [[], ["外部情報", "連結"]] + [
        [i.get("title", ""), i.get("url", "")] for i in digest["intel"] if isinstance(i, dict)
    ]
    if digest.get("intel_note"):
        rows.append([digest["intel_note"]])
    rows += [[], ["資料品質提醒"]] + (
        [[x] for x in digest["data_quality"]] or [["沒有資料品質提醒。"]]
    )
    if digest["data_quality_more"]:
        rows.append([f"（其餘 {digest['data_quality_more']} 項，見各系統報表）"])
    tabs.append(Tab(names["digest"], rows))

    stale = _system_note(digest, "progress")
    for key, sheet in (("alerts", "預警清單"), ("projects", "項目明細")):
        if progress_xlsx is None or stale:
            why = stale or "項目進度看板本週沒有產生報表"
            tabs.append(
                Tab(names[key], [top, [f"{why}，本頁未更新"]], [f"「{names[key]}」未更新：{why}"])
            )
            continue
        header, data = read_sheet_table(progress_xlsx, sheet)
        notes = [f"「{names[key]}」沒有任何資料列"] if not data and key == "projects" else []
        tabs.append(Tab(names[key], [top, [f"來源：{progress_xlsx.name}"], header, *data], notes))

    stale = _system_note(digest, "intel")
    if intel_xlsx is None or stale:
        why = stale or "外部情報沒有產生追蹤表"
        tabs.append(
            Tab(
                names["intel"],
                [top, [f"{why}，本頁未更新"]],
                [f"「{names['intel']}」未更新：{why}"],
            )
        )
    else:
        header, data = read_sheet_table(intel_xlsx, "追蹤表", INTEL_REQUIRED)
        idx = [header.index(c) for c in INTEL_COLUMNS if c in header]
        lost = [c for c in INTEL_COLUMNS if c not in header]
        notes = [f"情報追蹤表缺少欄位：{'、'.join(lost)}（其他欄位照常同步）"] if lost else []
        body = [[r[i] if i < len(r) else MISSING for i in idx] for r in data]
        tabs.append(
            Tab(
                names["intel"],
                [top, [f"來源：{intel_xlsx.name}"], [header[i] for i in idx], *body],
                notes,
            )
        )

    info = [
        top,
        [
            "本試算表由管理層系統每週自動寫入（單向）。請勿在系統分頁中編輯，下次同步會被覆蓋；可另外新增自己的分頁。"
        ],
        [],
    ]
    info += [[line] for line in digest["footer"]]
    tabs.append(Tab(names["info"], info))
    return tabs


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _num(v: object) -> object:
    """指標歷史裡的數字以數字寫入，才能畫趨勢圖。"""
    if isinstance(v, str) and _NUM.match(v.strip()):
        return float(v) if "." in v else int(v)
    return v


def history_row(digest: dict) -> tuple[list[str], list]:
    header = [HISTORY_MARK] + [m["label"] for m in digest["metrics"]] + ["資料等級"]
    row = [digest["as_of"]] + [_num(m["this"]) for m in digest["metrics"]] + [digest["level"]]
    return header, row


def _date_key(v: object) -> str | None:
    try:
        return parse_date(str(v).strip()).isoformat()
    except DateParseError:
        return None


def merge_history(
    existing: list[list], header: list[str], row: list
) -> tuple[list[list], list[str]]:
    """把本週那一列併入指標歷史。

    - 同一週覆蓋、不同週新增；日期寫法不同（例如 2026/10/07）視為同一週。
    - 第一欄不是日期的列（例如主管的註記）原樣保留在最後；超出表頭的格子原樣保留。
    - 看不懂的格式（第 1 列不是「週報日期」開頭）不改動，回傳提醒。
    """
    existing = [list(r) for r in existing]
    while existing and not any(str(c).strip() for c in existing[-1]):
        existing.pop()
    if not existing:
        return [list(header), list(row)], []
    old_header = [str(c).strip() for c in existing[0]]
    if not old_header or old_header[0] != HISTORY_MARK:
        return existing, [
            "「指標歷史」分頁的第 1 列不是系統的表頭（第一格應為「週報日期」），本週未更新這一頁"
        ]
    cols = list(old_header)
    for c in header:
        if c not in cols:
            cols.append(c)
    records: dict[str, list] = {}
    others: list[list] = []
    for r in existing[1:]:
        key = _date_key(r[0]) if r and str(r[0]).strip() else None
        if key is None:
            others.append(r)
            continue
        rec = list(r) + [""] * max(0, len(cols) - len(r))
        rec[0] = key
        records[key] = rec
    cur = records.get(row[0], [row[0]] + [""] * (len(cols) - 1))
    cur = cur + [""] * max(0, len(cols) - len(cur))
    for name, v in zip(header, row, strict=True):
        cur[cols.index(name)] = v
    records[row[0]] = cur
    out = [cols] + [records[k] for k in sorted(records)] + others
    return out, []
