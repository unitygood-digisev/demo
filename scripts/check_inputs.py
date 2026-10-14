"""輸入檔健檢：讀一個資料夾裡的 Excel，列出所有資料品質問題，產生報表。

目前只認得系統 1 的三個檔案（projects、milestones、updates）。
階段 2 實作系統 1 時，欄位定義會搬到 src/progress/。

執行：
  .venv/bin/python scripts/check_inputs.py data/sample/progress
  .venv/bin/python scripts/check_inputs.py data/raw --as-of 2026-10-14
輸出：data/out/check/資料品質檢查.xlsx 與 .md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from shared import logging as runlog  # noqa: E402
from shared.dates import today_tw  # noqa: E402
from shared.io import ColumnSpec, LoadResult, TableSpec, issues_frame, load_table  # noqa: E402
from shared.report import Footer, Section, make_run_id, write_md, write_xlsx  # noqa: E402

PROGRESS_SPECS: dict[str, TableSpec] = {
    "projects.xlsx": TableSpec(
        "projects",
        (
            ColumnSpec("project_id", label="項目編號"),
            ColumnSpec("客戶"),
            ColumnSpec("專案名稱"),
            ColumnSpec("負責人"),
            ColumnSpec("起始日", "date"),
            ColumnSpec("預計結案日", "date"),
            ColumnSpec("狀態", "enum", allowed=("未開始", "進行中", "已結案", "暫停")),
        ),
        unique_key="project_id",
    ),
    "milestones.xlsx": TableSpec(
        "milestones",
        (
            ColumnSpec("project_id"),
            ColumnSpec("里程碑名稱"),
            ColumnSpec("預計日", "date"),
            ColumnSpec("實際完成日", "date", required=False),
            ColumnSpec("狀態"),
        ),
    ),
    "updates.xlsx": TableSpec(
        "updates",
        (ColumnSpec("project_id"), ColumnSpec("更新日", "date"), ColumnSpec("備註")),
    ),
}


def check_dir(folder: Path, specs: dict[str, TableSpec]) -> dict[str, LoadResult]:
    return {name: load_table(folder / name, spec) for name, spec in specs.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="輸入檔健檢")
    ap.add_argument("folder", type=Path)
    ap.add_argument("--as-of", default=None, help="資料截至日期 YYYY-MM-DD，預設台灣今天")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "out" / "check")
    args = ap.parse_args(argv)

    as_of = today_tw(args.as_of)
    files = [args.folder / n for n in PROGRESS_SPECS]
    run_id = make_run_id("check", as_of, files)
    log = runlog.get_logger(run_id)
    results = check_dir(args.folder, PROGRESS_SPECS)
    issues = [i for r in results.values() for i in r.issues]
    for i in issues:
        log.warning("資料品質：%s 第 %s 列 %s %s", i.file, i.row, i.column, i.problem)

    headline = (
        f"輸入檔共有 {len(issues)} 個資料問題，請先修正再產生看板。"
        if issues
        else "輸入檔檢查通過，沒有發現資料問題。"
    )
    summary = pd.DataFrame(
        [{"檔案": n, "讀到筆數": len(r.data), "問題數": len(r.issues)} for n, r in results.items()]
    )
    footer = Footer(
        as_of=as_of,
        input_files=[f.name for f in files],
        run_id=run_id,
        level="內部一般",
        missing=[f"{i.file} 第 {i.row} 列 {i.column}" for i in issues if i.row is not None],
    )
    dq = issues_frame(issues)
    xlsx = write_xlsx(
        args.out / "資料品質檢查.xlsx", headline, {"各檔摘要": summary, "資料品質": dq}, footer
    )
    md = write_md(
        args.out / "資料品質檢查.md",
        "輸入檔健檢",
        headline,
        [Section("各檔摘要", table=summary), Section("資料品質", table=dq)],
        footer,
    )
    print(headline)
    print(f"已產生：{xlsx}\n已產生：{md}")
    runlog.close_logger(log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
