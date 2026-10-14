"""管理層週報（系統 5）手動執行入口。

讀各系統最新的 summary.json，產生一頁週報：
    .venv/bin/python scripts/run_digest.py
用假資料試跑（先跑外部情報與項目進度的假資料，再產生週報）：
    .venv/bin/python scripts/run_digest.py --sample
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from digest.pipeline import RunConfig, run  # noqa: E402
from shared.dates import today_tw  # noqa: E402

SAMPLE_DAY = dt.date(2026, 10, 14)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="管理層週報")
    ap.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD，預設台灣今天")
    ap.add_argument(
        "--sample", action="store_true", help="用假資料試跑，輸出到 data/out/digest_sample"
    )
    args = ap.parse_args(argv)
    if args.sample:
        from scripts import run_intel, run_progress

        run_intel.main(["--sample", "--as-of", SAMPLE_DAY.isoformat(), "--weekly"])
        run_progress.main(["--sample"])
        cfg = RunConfig(
            as_of=SAMPLE_DAY,
            out_dir=ROOT / "data" / "out" / "digest_sample",
            summary_overrides={
                "intel": ROOT / "data" / "out" / "intel_sample" / "summary.json",
                "progress": ROOT / "data" / "out" / "progress_sample" / "summary.json",
            },
        )
    else:
        cfg = RunConfig(as_of=today_tw(args.as_of))
    result = run(cfg)
    print(result.digest.sentences[0])
    for path in result.files.values():
        print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
