"""歷次紀錄：每次執行存一份快照（各案狀態）與一份結果（預警與指標），供下次比較。

存在 data/interim/progress/：
- snapshots/YYYYMMDD.csv：案子、階段、下一步、下一個日期（不含卡點／風險、備註）
- runs/YYYYMMDD.json：預警清單與指標
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from progress.board import Board, ProgressDataError

SNAP_FIELDS = ["案子", "階段", "下一步", "下一個日期"]


def _day(p: Path) -> dt.date | None:
    try:
        return dt.datetime.strptime(p.stem, "%Y%m%d").date()
    except ValueError:
        return None


def _state(r: dict) -> tuple[str, str, str]:
    d = r.get("下一個日期")
    return (
        r.get("階段") or "",
        r.get("下一步") or "",
        d.isoformat() if isinstance(d, dt.date) else (d or ""),
    )


class History:
    def __init__(self, folder: Path) -> None:
        self.snap_dir = folder / "snapshots"
        self.run_dir = folder / "runs"

    # ---- 讀 ----
    def _dated(self, folder: Path, suffix: str) -> list[tuple[dt.date, Path]]:
        if not folder.exists():
            return []
        out = [(d, p) for p in folder.glob(f"*{suffix}") if (d := _day(p))]
        return sorted(out)

    def latest_run_date(self) -> dt.date | None:
        runs = self._dated(self.run_dir, ".json")
        return runs[-1][0] if runs else None

    def snapshots_before(self, as_of: dt.date) -> list[tuple[dt.date, dict[str, tuple]]]:
        out = []
        for d, p in self._dated(self.snap_dir, ".csv"):
            if d >= as_of:
                continue
            try:
                with p.open(encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames != SNAP_FIELDS:
                        raise ValueError
                    out.append(
                        (
                            d,
                            {
                                row["案子"]: (row["階段"], row["下一步"], row["下一個日期"])
                                for row in reader
                            },
                        )
                    )
            except (ValueError, KeyError, UnicodeDecodeError) as e:
                raise ProgressDataError(
                    f"中間檔 {p.name} 格式錯誤（可刪除此檔，但會少一次比較紀錄）"
                ) from e
        return out

    def previous_run(self, as_of: dt.date) -> tuple[dt.date, dict] | None:
        runs = [(d, p) for d, p in self._dated(self.run_dir, ".json") if d < as_of]
        if not runs:
            return None
        d, p = runs[-1]
        try:
            return d, json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ProgressDataError(
                f"中間檔 {p.name} 已損壞（可刪除此檔，但會少一次比較紀錄）"
            ) from e

    # ---- 計算 ----
    def unchanged_since(
        self, board: Board, as_of: dt.date
    ) -> tuple[dict[str, dt.date], dt.date | None]:
        """每案「從哪一天起狀態沒變」，以及最早一份快照的日期（判斷紀錄是否夠久）。"""
        snaps = self.snapshots_before(as_of)
        out: dict[str, dt.date] = {}
        for r in board.rows:
            name, cur = r["案子"], _state(r)
            since = None
            for d, states in reversed(snaps):
                if states.get(name) == cur:
                    since = d
                else:
                    break
            if since:
                out[name] = since
        return out, (snaps[0][0] if snaps else None)

    # ---- 寫 ----
    def save(self, as_of: dt.date, board: Board, run: dict) -> None:
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        stem = as_of.strftime("%Y%m%d")
        with (self.snap_dir / f"{stem}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(SNAP_FIELDS)
            for r in sorted(board.rows, key=lambda x: x["_row"]):
                if r["案子"] in board.duplicates:
                    continue
                w.writerow([r["案子"], *_state(r)])
        (self.run_dir / f"{stem}.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )


def compare(prev: dict | None, cur_alerts: list[dict], cur_projects: list[str]) -> dict:
    """與上次比較：預警新增／解除／持續；案子新增／消失。"""
    if prev is None:
        return {"available": False}
    key = lambda a: (a["rule"], a["subject"])  # noqa: E731
    prev_alerts = {key(a): a for a in prev["alerts"]}
    cur = {key(a): a for a in cur_alerts}
    prev_projects = set(prev.get("projects", []))
    return {
        "available": True,
        "new": [cur[k] for k in cur if k not in prev_alerts],
        "resolved": [prev_alerts[k] for k in prev_alerts if k not in cur],
        "ongoing": [cur[k] for k in cur if k in prev_alerts],
        "added_projects": sorted(p for p in cur_projects if p not in prev_projects),
        "removed_projects": sorted(p for p in prev_projects if p not in set(cur_projects)),
    }
