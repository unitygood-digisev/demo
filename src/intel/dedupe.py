"""去重：網址相同視為同一篇；標題相似度達門檻視為同一事件。"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from intel.urls import normalize_url
from shared.schema import NewsItem

_NON_WORD = re.compile(r"[\W_]+")
_FAR_FUTURE = dt.datetime.max.replace(tzinfo=dt.UTC)


def norm_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title).casefold()
    return _NON_WORD.sub("", t)


def title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


@dataclass
class Event:
    """一個事件：主文＋同一事件的其他報導。"""

    main: NewsItem
    others: list[NewsItem] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.main.id

    @property
    def members(self) -> list[NewsItem]:
        return [self.main, *self.others]

    @property
    def member_ids(self) -> list[str]:
        return sorted({m.id for m in self.members})

    @property
    def source_ids(self) -> list[str]:
        out: list[str] = []
        for m in self.members:
            if m.source_id not in out:
                out.append(m.source_id)
        return out

    @property
    def extra_urls(self) -> list[str]:
        """其他報導的連結（網址正規化後與主文不同者）。"""
        seen = {normalize_url(self.main.url)}
        out: list[str] = []
        for m in self.others:
            n = normalize_url(m.url)
            if n not in seen:
                seen.add(n)
                out.append(m.url)
        return out


def _order_key(item: NewsItem, source_rank: dict[str, int]) -> tuple:
    # 最早發布者當主文；沒有發布時間的排最後；再依來源順序、編號，確保結果固定
    return (item.published or _FAR_FUTURE, source_rank.get(item.source_id, 999), item.id)


def dedupe(
    items: list[NewsItem], source_rank: dict[str, int], threshold: float | None
) -> list[Event]:
    ordered = sorted(items, key=lambda x: _order_key(x, source_rank))
    # 1. 網址相同
    by_url: dict[str, Event] = {}
    events: list[Event] = []
    for it in ordered:
        key = normalize_url(it.url)
        if key in by_url:
            by_url[key].others.append(it)
        else:
            ev = Event(it)
            by_url[key] = ev
            events.append(ev)
    if threshold is None:
        return events
    # 2. 標題相似（依時間順序，併入第一個相似的事件）
    merged: list[Event] = []
    for ev in events:
        target = next(
            (m for m in merged if title_similarity(m.main.title, ev.main.title) >= threshold), None
        )
        if target is None:
            merged.append(ev)
        else:
            target.others.extend(ev.members)
    return merged
