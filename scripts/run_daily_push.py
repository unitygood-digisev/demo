"""每日情報郵件（階段 1b）手動執行入口。排程設定見 docs/handover/daily_push.md。

每天（建議週一到週五早上 8:00）：
    .venv/bin/python scripts/run_daily_push.py
只產生郵件草稿、不寄出：
    .venv/bin/python scripts/run_daily_push.py --draft-only
用假資料試跑（不連網路、不寄信）：
    .venv/bin/python scripts/run_daily_push.py --sample

結束代碼：0＝已寄出或今天已寄過；2＝沒有寄出（未設定、只產生草稿或沒有來源）；1＝錯誤。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intel.daily_push import PushConfig, run  # noqa: E402
from intel.store import IntelDataError  # noqa: E402
from shared.dates import DateParseError, today_tw  # noqa: E402
from shared.mail_client import MailError  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "feeds"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每日情報郵件")
    ap.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD，預設台灣今天")
    ap.add_argument("--draft-only", action="store_true", help="只產生郵件草稿，不寄出")
    ap.add_argument("--sample", action="store_true", help="用假資料試跑（不連網路、不寄信）")
    args = ap.parse_args(argv)
    try:
        as_of = today_tw(args.as_of)
    except (DateParseError, ValueError):
        print(f"未執行：--as-of「{args.as_of}」不是正確的日期，請寫成 YYYY-MM-DD")
        return 1
    cfg = PushConfig(as_of=as_of, send=not args.draft_only)
    if args.sample:
        cfg.sources_path = SAMPLE / "sources_sample.yaml"
        cfg.keywords_path = SAMPLE / "keywords_sample.yaml"
        cfg.interim_dir = ROOT / "data" / "interim" / "intel_sample_push"
        cfg.out_dir = ROOT / "data" / "out" / "intel_sample_push"
        cfg.offline, cfg.send = True, False
    try:
        res = run(cfg)
    except (IntelDataError, MailError) as e:
        print(f"未執行：{e}")
        return 1
    print(res.message)
    print(f"郵件內容：{res.draft}")
    return 0 if res.message in ("已寄出", "今天已經寄過，沒有重寄") else 2


if __name__ == "__main__":
    raise SystemExit(main())
