"""把本週報表同步到公司 Google 試算表（單向寫入）。

    .venv/bin/python scripts/sync_sheets.py
    .venv/bin/python scripts/sync_sheets.py --as-of 2026-10-14
不連 Google、先看會寫入什麼（每個分頁存成一個 CSV）：
    .venv/bin/python scripts/sync_sheets.py --preview
設定步驟見 docs/handover/google_sheets.md
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shared.dates import today_tw  # noqa: E402
from sheets.client import FakeClient  # noqa: E402
from sheets.content import SyncError  # noqa: E402
from sheets.sync import SyncConfig, sync  # noqa: E402

SKIPPED = 2  # 未設定而略過（不是失敗）


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步到 Google 試算表")
    ap.add_argument("--as-of", default=None, help="週報日期 YYYY-MM-DD，預設台灣今天")
    ap.add_argument(
        "--preview",
        action="store_true",
        help="不連 Google，把每個分頁存成 CSV 到 data/out/sheets_preview/",
    )
    args = ap.parse_args(argv)
    cfg = SyncConfig(as_of=today_tw(args.as_of))
    fake = FakeClient() if args.preview else None
    cfg.client = fake
    try:
        titles = sync(cfg)
    except SyncError as e:
        msg = str(e)
        print(f"未同步：{msg}")
        return SKIPPED if "略過同步" in msg else 1
    if fake is not None:
        out = ROOT / "data" / "out" / "sheets_preview"
        out.mkdir(parents=True, exist_ok=True)
        for title, rows in fake.tabs.items():
            with (out / f"{title}.csv").open("w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(rows)
        print(f"預覽完成（沒有連 Google）：{out}")
    else:
        print(f"已同步到 Google 試算表：{'、'.join(titles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
