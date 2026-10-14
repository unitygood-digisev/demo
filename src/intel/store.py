"""中間結果：看過的文章（seen.csv）與每日處理結果（days/YYYYMMDD.json）。

中間檔被改壞時，丟出 IntelDataError（白話說明哪個檔案、哪一列），不默默略過。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path


class IntelDataError(Exception):
    """中間檔或執行條件有問題，需要人處理。訊息為白話中文。"""


class SeenStore:
    """記錄每篇文章第一次被看到的日期，用來避免跨次執行重複。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.first_seen: dict[str, dt.date] = {}
        if not path.exists():
            return
        hint = "（若無法修復，可刪除此檔，但所有文章會被當成新文章重新列出）"
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not {"id", "first_seen"} <= set(reader.fieldnames):
                raise IntelDataError(f"中間檔 {path.name} 第 1 列應為「id,first_seen」{hint}")
            for n, row in enumerate(reader, start=2):
                try:
                    i = (row["id"] or "").strip()
                    d = dt.date.fromisoformat((row["first_seen"] or "").strip())
                except (ValueError, TypeError) as e:
                    raise IntelDataError(
                        f"中間檔 {path.name} 第 {n} 列日期格式錯誤（應為 YYYY-MM-DD）{hint}"
                    ) from e
                if not i:
                    raise IntelDataError(f"中間檔 {path.name} 第 {n} 列缺少文章編號{hint}")
                self.first_seen[i] = d

    @property
    def latest(self) -> dt.date | None:
        return max(self.first_seen.values()) if self.first_seen else None

    def first_seen_of(self, ids: list[str], default: dt.date) -> dt.date:
        dates = [self.first_seen[i] for i in ids if i in self.first_seen]
        return min(dates) if dates else default

    def is_new(self, item_id: str, day: dt.date) -> bool:
        return self.first_seen.get(item_id, day) == day

    def mark(self, ids: list[str], day: dt.date) -> None:
        """只記錄第一次看到的日期，已記錄的不改。"""
        for i in ids:
            self.first_seen.setdefault(i, day)

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

    def _read(self, p: Path) -> dict:
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise IntelDataError(
                f"中間檔 {p.name} 已損壞，無法讀取（可刪除此檔後重跑那一天）"
            ) from e
        if not isinstance(data, dict) or "records" not in data:
            raise IntelDataError(f"中間檔 {p.name} 內容不完整（可刪除此檔後重跑那一天）")
        return data

    def load(self, day: dt.date) -> dict | None:
        p = self.path(day)
        return self._read(p) if p.exists() else None

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
                out.append(self._read(p))
        return out
