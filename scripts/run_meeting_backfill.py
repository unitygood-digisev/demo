"""會議紀錄 → 看板補齊建議（階段 2b）手動執行入口。

每月開完會、把紀錄（UTF-8 文字檔）放進 data/raw/meetings/ 後：
    .venv/bin/python scripts/run_meeting_backfill.py
用假資料試跑：
    .venv/bin/python scripts/run_meeting_backfill.py --sample
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from progress.backfill import BackfillConfig, run  # noqa: E402
from progress.board import ProgressDataError  # noqa: E402
from shared.dates import DateParseError, parse_date, today_tw  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "progress"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="用會議紀錄產生看板補齊建議（不改看板）")
    ap.add_argument("--sample", action="store_true", help="用假資料試跑")
    ap.add_argument("--as-of", help="執行日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--board", help="指定看板檔（預設 data/raw/ 最新一份）")
    a = ap.parse_args(argv)
    try:
        as_of = parse_date(a.as_of) if a.as_of else today_tw()
    except DateParseError:
        print(f"未執行：--as-of「{a.as_of}」不是正確的日期，請寫成 YYYY-MM-DD")
        return 1
    if a.sample:
        cfg = BackfillConfig(
            as_of=as_of,
            board_path=SAMPLE / "項目進度看板_假資料_20261014.xlsx",
            meetings_dir=SAMPLE / "meetings",
            aliases_path=SAMPLE / "meeting_aliases_sample.yaml",
            out_dir=ROOT / "data" / "out" / "progress_sample",
        )
    else:
        cfg = BackfillConfig(as_of=as_of, board_path=Path(a.board) if a.board else None)
    try:
        res = run(cfg)
    except ProgressDataError as e:
        print(f"未執行：{e}")
        return 1
    print(res.headline)
    print(f"輸出：{res.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
