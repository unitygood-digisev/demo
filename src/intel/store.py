"""中間結果：看過的文章（seen.csv）與每日處理結果（days/YYYYMMDD.json）。"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path


class SeenStore:
    """記錄每篇文章第一次被看到的日期，用來避免跨次執行重複。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.first_seen: dict[str, dt.date] = {}
        if path.exists():
            with path.open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    self.first_seen[row["id"]] = dt.date.fromisoformat(row["first_seen"])

    def first_seen_of(self, ids: list[str], default: dt.date) -> dt.date:
        dates = [self.first_seen[i] for i in ids if i in self.first_seen]
        return min(dates) if dates else default

    def mark(self, ids: list[str], day: dt.date) -> None:
        for i in ids:
            if i not in self.first_seen or day < self.first_seen[i]:
                self.first_seen[i] = day

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "first_seen"])
            for i, d in sorted(self.first_seen.items()):
                w.writerow([i, d.isoformat()])
        tmp.replace(self.path)


class DayStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, day: dt.date) -> Path:
        return self.folder / f"{day.strftime('%Y%m%d')}.json"

    def save(self, day: dt.date, data: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(day).write_text(
            json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )

    def load(self, day: dt.date) -> dict | None:
        p = self.path(day)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def window(self, end: dt.date, days: int) -> list[dict]:
        out = []
        for k in range(days - 1, -1, -1):
            d = self.load(end - dt.timedelta(days=k))
            if d is not None:
                out.append(d)
        return out

    def all_until(self, end: dt.date) -> list[dict]:
        out = []
        for p in sorted(self.folder.glob("*.json")) if self.folder.exists() else []:
            try:
                day = dt.datetime.strptime(p.stem, "%Y%m%d").date()
            except ValueError:
                continue
            if day <= end:
                out.append(json.loads(p.read_text(encoding="utf-8")))
        return out
