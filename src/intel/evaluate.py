"""用主管標記的文章，計算不同相關度門檻下的精確率與召回率。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook

LABEL_SHEET = "標記"
LABEL_COLUMNS = ["文章編號", "標題", "來源", "連結", "系統分數", "標記（相關／不相關）"]
VALID = ("相關", "不相關")


@dataclass(frozen=True)
class Row:
    threshold: int
    selected: int
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None


def make_sheet(records: list[dict], path: Path, limit: int = 30) -> Path:
    """產生給主管標記的 Excel。不顯示系統判斷結果以外的資訊，避免影響判斷。"""
    wb = Workbook()
    ws = wb.active
    ws.title = LABEL_SHEET
    ws.append(LABEL_COLUMNS)
    for r in records[:limit]:
        ws.append([r["id"], r["title"], "、".join(r["sources"]), r["url"], r["score"], ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def read_labels(path: Path) -> tuple[dict[str, bool], list[str]]:
    ws = load_workbook(path, read_only=True)[LABEL_SHEET]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c or "") for c in rows[0]]
    i_id, i_lab = header.index("文章編號"), header.index("標記（相關／不相關）")
    labels: dict[str, bool] = {}
    problems: list[str] = []
    for n, row in enumerate(rows[1:], start=2):
        if not row or not row[i_id]:
            continue
        lab = str(row[i_lab] or "").strip()
        if lab not in VALID:
            problems.append(f"第 {n} 列的標記「{lab or '空白'}」不是「相關」或「不相關」，未計入")
            continue
        labels[str(row[i_id])] = lab == "相關"
    return labels, problems


def evaluate(scores: dict[str, int], labels: dict[str, bool]) -> tuple[list[Row], list[str]]:
    missing = sorted(i for i in labels if i not in scores)
    ids = [i for i in labels if i in scores]
    thresholds = sorted({max(1, scores[i]) for i in ids} | {1})
    rows = []
    for t in thresholds:
        sel = {i for i in ids if scores[i] >= t}
        tp = sum(1 for i in sel if labels[i])
        fp = len(sel) - tp
        fn = sum(1 for i in ids if labels[i] and i not in sel)
        rows.append(Row(t, len(sel), tp, fp, fn))
    probs = [f"文章編號 {i} 找不到系統分數，未計入" for i in missing]
    return rows, probs


def to_markdown(rows: list[Row], n_labels: int, problems: list[str], as_of: str) -> str:
    def pct(v: float | None) -> str:
        return "待補" if v is None else f"{v:.0%}"

    out = [
        "# 外部情報相關度評估",
        "",
        f"資料截至：{as_of}　已標記文章：{n_labels} 篇",
        "",
        "- 精確率：系統選中的文章中，主管也認為相關的比例（越高越不雜）。",
        "- 召回率：主管認為相關的文章中，系統有選中的比例（越高越不漏）。",
        "",
        "| 門檻（分數 ≥） | 選中篇數 | 正確選中 | 選錯 | 漏掉 | 精確率 | 召回率 |",
        "|---|---|---|---|---|---|---|",
    ]
    out += [
        f"| {r.threshold} | {r.selected} | {r.tp} | {r.fp} | {r.fn} | {pct(r.precision)} | {pct(r.recall)} |"
        for r in rows
    ]
    out += ["", "## 資料問題", ""] + ([f"- {p}" for p in problems] or ["無"])
    return "\n".join(out) + "\n"
