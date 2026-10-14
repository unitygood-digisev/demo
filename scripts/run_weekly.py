"""每週一鍵執行：外部情報（含每週彙整）→ 項目進度看板 → 管理層週報。

    .venv/bin/python scripts/run_weekly.py
    .venv/bin/python scripts/run_weekly.py --as-of 2026-10-19

前面某個系統失敗時，其他照跑；週報會把失敗的系統標成「本週執行失敗，未納入」，
不會拿上週的舊數字充當本週。目前只提供手動執行，不設排程。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts import run_digest, run_intel, run_progress  # noqa: E402

# (系統代號, 名稱, 執行函式, 額外參數)
STEPS = [
    ("intel", "外部情報摘要", run_intel.main, ["--weekly"]),
    ("progress", "項目進度看板", run_progress.main, []),
]
DIGEST = ("管理層週報", run_digest.main)


def _call(name, fn, argv) -> int:
    try:
        code = fn(argv)
    except SystemExit as e:  # 參數錯誤等中止，也不影響後面的步驟
        code = e.code if isinstance(e.code, int) else 1
    except Exception as e:  # noqa: BLE001
        print(f"未完成：{name} 發生錯誤（{type(e).__name__}），請把這段訊息給負責人")
        code = 1
    return code or 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每週一鍵執行")
    ap.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD，預設台灣今天")
    args = ap.parse_args(argv)
    date_args = ["--as-of", args.as_of] if args.as_of else []
    failed: list[tuple[str, str]] = []
    for key, name, fn, extra in STEPS:
        print(f"=== {name} ===")
        if _call(name, fn, extra + date_args):
            failed.append((key, name))
    print(f"=== {DIGEST[0]} ===")
    digest_args = date_args + (["--failed", ",".join(k for k, _ in failed)] if failed else [])
    digest_failed = _call(DIGEST[0], DIGEST[1], digest_args)
    print("=== 結果 ===")
    names = [n for _, n in failed] + ([DIGEST[0]] if digest_failed else [])
    if not names:
        print("全部完成。")
        return 0
    note = "（週報中已標示為「本週執行失敗，未納入」）" if failed and not digest_failed else ""
    print(f"以下步驟未完成：{'、'.join(names)}{note}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
