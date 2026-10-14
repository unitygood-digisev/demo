"""預警規則 P01–P05 與資料品質檢查。所有門檻來自 config/thresholds.yaml。"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field

from progress.board import Board, BoardConfig

LIGHT_ORDER = {"紅": 0, "黃": 1, "綠": 2}
RULE_NAMES = {
    "P01": "下一步日期已過",
    "P02": "下一步即將到期",
    "P03": "卡關",
    "P04": "長期沒有變化",
    "P05": "負責案數偏多",
}
_PAREN = re.compile(r"[（(][^）)]*[）)]")
_SPLIT = re.compile(r"[、／/,，;；]")


@dataclass(frozen=True)
class Alert:
    level: str
    rule: str
    subject: str  # 案子名稱，或 P05 的負責人
    why: str
    suggested_owner: str
    row: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.rule, self.subject)


@dataclass(frozen=True)
class Quality:
    row: int | None
    project: str
    field: str
    problem: str


@dataclass
class Evaluation:
    alerts: list[Alert] = field(default_factory=list)
    quality: list[Quality] = field(default_factory=list)
    owner_counts: dict[str, list[str]] = field(default_factory=dict)
    lights: dict[int, str] = field(default_factory=dict)  # Excel 列號 → 燈號
    notes: list[str] = field(default_factory=list)  # 待補說明


def owners_of(text: str | None, cfg: BoardConfig) -> list[str]:
    """括號外的人名才算負責人；「、」「／」分開的都算；非人名（如行政）不算。"""
    if not text:
        return []
    out = []
    for p in _SPLIT.split(_PAREN.sub("", text)):
        p = p.strip()
        if p and p not in cfg.non_person_owners and p not in out:
            out.append(p)
    return out


def _owner_text(r: dict) -> str:
    return r.get("負責人") or "待補（負責人空白）"


def evaluate(
    board: Board,
    as_of: dt.date,
    cfg: BoardConfig,
    th: dict,
    unchanged_since: dict[str, dt.date],
    history_ok: bool,
) -> Evaluation:
    ev = Evaluation()
    due_n = th["P02_due_soon_days"]
    stale_n = th["P04_unchanged_days"]
    max_n = th["P05_max_active_projects"]
    owner_projects: dict[str, list[str]] = defaultdict(list)

    for r in board.rows:
        name, stage, d = r["案子"], r.get("階段"), r.get("下一個日期")
        row = int(r["_row"])
        done = stage in cfg.done_stages
        active = stage in cfg.active_stages
        if d is not None and not done:
            days = (d - as_of).days
            if days < 0:
                ev.alerts.append(
                    Alert(
                        "紅",
                        "P01",
                        name,
                        f"下一步日期 {d.isoformat()} 已過 {-days} 天，階段仍是「{stage or '待補'}」",
                        _owner_text(r),
                        row,
                    )
                )
            elif due_n is not None and days <= due_n:
                when = "今天到期" if days == 0 else f"還有 {days} 天"
                ev.alerts.append(
                    Alert(
                        "黃",
                        "P02",
                        name,
                        f"下一步日期 {d.isoformat()}，{when}",
                        _owner_text(r),
                        row,
                    )
                )
        if stage in cfg.blocked_stages:
            ev.alerts.append(Alert("紅", "P03", name, f"階段為「{stage}」", _owner_text(r), row))
        if active and stale_n is not None and name not in board.duplicates:
            since = unchanged_since.get(name)
            if since is not None and (as_of - since).days >= stale_n:
                ev.alerts.append(
                    Alert(
                        "黃",
                        "P04",
                        name,
                        f"自 {since.isoformat()} 起連續 {(as_of - since).days} 天，階段、下一步、日期都沒有變化",
                        _owner_text(r),
                        row,
                    )
                )
        # 資料品質
        if active and d is None:
            ev.quality.append(
                Quality(row, name, "下一個日期", "進行中的案子沒有下一個日期，無法判斷是否延誤")
            )
        if active and not r.get("負責人"):
            ev.quality.append(Quality(row, name, "負責人", "進行中的案子沒有負責人"))
        if active:
            for o in owners_of(r.get("負責人"), cfg):
                owner_projects[o].append(name)

    if stale_n is not None and not history_ok:
        ev.notes.append(f"歷次快照不足 {stale_n} 天，「長期沒有變化」（P04）可能漏報")
    if stale_n is None:
        ev.notes.append("P04 門檻未設定，未檢查長期沒有變化")
    if due_n is None:
        ev.notes.append("P02 門檻未設定，未檢查即將到期的案子")
    if max_n is None:
        ev.notes.append("P05 門檻未設定，未檢查負責案數")

    ev.owner_counts = {o: owner_projects[o] for o in sorted(owner_projects)}
    if max_n is not None:
        for o, ps in ev.owner_counts.items():
            if len(ps) > max_n:
                ev.alerts.append(
                    Alert(
                        "黃",
                        "P05",
                        o,
                        f"目前負責 {len(ps)} 個進行中的案子（門檻 {max_n}）",
                        "部門主管（排程參考，不是績效評估）",
                    )
                )

    # 每列燈號＝該列預警中最嚴重者
    for a in ev.alerts:
        if a.row is not None:
            cur = ev.lights.get(a.row, "綠")
            if LIGHT_ORDER[a.level] < LIGHT_ORDER[cur]:
                ev.lights[a.row] = a.level
    for r in board.rows:
        ev.lights.setdefault(int(r["_row"]), "綠")
    ev.alerts.sort(key=lambda a: (LIGHT_ORDER[a.level], a.rule, a.row or 0, a.subject))
    return ev
