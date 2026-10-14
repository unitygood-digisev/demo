"""外部情報相關度評估。

步驟 1：產生標記表（給主管填「相關／不相關」）
  .venv/bin/python scripts/intel_eval.py make-sheet
步驟 2：主管填好後計算精確率、召回率，結果寫到 docs/intel_eval.md
  .venv/bin/python scripts/intel_eval.py score data/out/intel/標記表.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from intel.evaluate import evaluate, make_sheet, read_labels, to_markdown  # noqa: E402
from intel.store import DayStore  # noqa: E402
from shared.dates import today_tw  # noqa: E402


def _records(interim: Path, as_of) -> list[dict]:
    recs = [r for d in DayStore(interim / "days").all_until(as_of) for r in d["records"]]
    return sorted(recs, key=lambda r: (r["first_seen"], r["id"]), reverse=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="外部情報相關度評估")
    ap.add_argument("action", choices=["make-sheet", "score"])
    ap.add_argument("labels", nargs="?", type=Path)
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--interim", type=Path, default=ROOT / "data" / "interim" / "intel")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    as_of = today_tw(args.as_of)
    recs = _records(args.interim, as_of)

    if args.action == "make-sheet":
        out = args.out or ROOT / "data" / "out" / "intel" / "標記表.xlsx"
        make_sheet(recs, out)
        print(f"已產生標記表（{min(len(recs), 30)} 篇）：{out}")
        return 0
    if not args.labels:
        ap.error("請指定已填好的標記表路徑")
    labels, problems = read_labels(args.labels)
    rows, more = evaluate({r["id"]: r["score"] for r in recs}, labels)
    out = args.out or ROOT / "docs" / "intel_eval.md"
    out.write_text(
        to_markdown(rows, len(labels), problems + more, as_of.isoformat()), encoding="utf-8"
    )
    print(f"已寫入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
