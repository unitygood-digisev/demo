"""每週一鍵執行：外部情報（含每週彙整）→ 項目進度看板 → 管理層週報。

    .venv/bin/python scripts/run_weekly.py

某個系統失敗時，其他照跑；週報會寫出哪個系統本週未更新。
目前只提供手動執行，不設排程。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts import run_digest, run_intel, run_progress  # noqa: E402

STEPS = [
    ("外部情報摘要", run_intel.main, ["--weekly"]),
    ("項目進度看板", run_progress.main, []),
    ("管理層週報", run_digest.main, []),
]


def main(argv: list[str] | None = None) -> int:
    failed = []
    for name, fn, args in STEPS:
        print(f"=== {name} ===")
        try:
            code = fn(list(args) + list(argv or []) if name != "管理層週報" else list(argv or []))
        except Exception as e:  # 某一步出錯不影響其他步驟
            print(f"未完成：{name} 發生錯誤（{type(e).__name__}），請把這段訊息給負責人")
            code = 1
        if code:
            failed.append(name)
    print("=== 結果 ===")
    print(
        "全部完成。"
        if not failed
        else f"以下步驟未完成：{'、'.join(failed)}（週報中會標示「本週未更新」）"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
