"""項目進度看板（系統 1）手動執行入口。

每週（看板更新後）：
    .venv/bin/python scripts/run_progress.py
指定看板檔或日期：
    .venv/bin/python scripts/run_progress.py --input data/raw/項目進度看板_20261005.xlsx --as-of 2026-10-14
用假資料試跑（依序跑 9/30、10/7、10/14 三週，示範與上週比較）：
    .venv/bin/python scripts/run_progress.py --sample
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from progress.board import ProgressDataError  # noqa: E402
from progress.pipeline import RunConfig, run  # noqa: E402
from shared.dates import today_tw  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "progress"
SAMPLE_WEEKS = (dt.date(2026, 9, 30), dt.date(2026, 10, 7), dt.date(2026, 10, 14))


def run_sample(interim: Path, out: Path):
    """清空假資料的中間檔，依序跑三週。"""
    shutil.rmtree(interim, ignore_errors=True)
    result = None
    for day in SAMPLE_WEEKS:
        path = SAMPLE / f"項目進度看板_假資料_{day.strftime('%Y%m%d')}.xlsx"
        result = run(RunConfig(as_of=day, input_path=path, interim_dir=interim, out_dir=out))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="項目進度看板")
    ap.add_argument(
        "--input", type=Path, default=None, help="看板 Excel，預設取 data/raw/ 下最新的"
    )
    ap.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD，預設台灣今天")
    ap.add_argument(
        "--sample", action="store_true", help="用假資料試跑三週，輸出到 data/out/progress_sample"
    )
    args = ap.parse_args(argv)
    try:
        if args.sample:
            result = run_sample(
                ROOT / "data" / "interim" / "progress_sample",
                ROOT / "data" / "out" / "progress_sample",
            )
        else:
            result = run(RunConfig(as_of=today_tw(args.as_of), input_path=args.input))
    except ProgressDataError as e:
        print(f"未執行：{e}")
        return 1
    print(result.files["md"].read_text(encoding="utf-8").splitlines()[4].strip("*"))
    for path in result.files.values():
        print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
