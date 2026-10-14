"""外部情報摘要（系統 7）手動執行入口。

每天：  .venv/bin/python scripts/run_intel.py
每週：  .venv/bin/python scripts/run_intel.py --weekly
假資料試跑（不連網路）：
        .venv/bin/python scripts/run_intel.py --sample --as-of 2026-10-14 --weekly
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intel.pipeline import RunConfig, run  # noqa: E402
from shared.dates import today_tw  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "feeds"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="外部情報摘要")
    ap.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD，預設台灣今天")
    ap.add_argument("--weekly", action="store_true", help="另外產生每週彙整 Word 檔")
    ap.add_argument("--offline", action="store_true", help="不連網路，只讀本機檔與今天的快取")
    ap.add_argument(
        "--sample",
        action="store_true",
        help="用假資料試跑（不連網路，輸出到 data/out/intel_sample）",
    )
    ap.add_argument("--sources", type=Path, default=None)
    ap.add_argument("--keywords", type=Path, default=None)
    args = ap.parse_args(argv)

    cfg = RunConfig(as_of=today_tw(args.as_of), offline=args.offline, weekly=args.weekly)
    if args.sample:
        cfg.sources_path = SAMPLE / "sources_sample.yaml"
        cfg.keywords_path = SAMPLE / "keywords_sample.yaml"
        cfg.interim_dir = ROOT / "data" / "interim" / "intel_sample"
        cfg.out_dir = ROOT / "data" / "out" / "intel_sample"
        cfg.offline = True
    if args.sources:
        cfg.sources_path = args.sources
    if args.keywords:
        cfg.keywords_path = args.keywords

    result = run(cfg)
    print(Path(result.files["daily"]).read_text(encoding="utf-8").splitlines()[4].strip("*"))
    for path in result.files.values():
        print(f"已產生：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
