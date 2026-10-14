"""把 RSS 文章整理成 NewsItem。"""

from __future__ import annotations

import calendar
import datetime as dt
import html
import re

from intel.fetch import FetchResult
from intel.urls import item_id
from shared.dates import TW_TZ
from shared.schema import NewsItem

EXCERPT_MAX = 1000
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return _SPACE.sub(" ", s).strip()


def _published(entry) -> dt.datetime | None:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(st), dt.UTC).astimezone(TW_TZ)


def to_items(result: FetchResult, fetched_at: dt.datetime) -> tuple[list[NewsItem], list[str]]:
    """回傳 (文章, 問題清單)。沒有標題或網址的文章列為問題，不默默丟掉。"""
    items: list[NewsItem] = []
    problems: list[str] = []
    for i, e in enumerate(result.entries, start=1):
        title = clean_text(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link.lower().startswith(("http://", "https://")):
            problems.append(f"{result.source.name} 第 {i} 則缺少標題或有效網址，未納入")
            continue
        excerpt = clean_text(e.get("summary") or e.get("description"))[:EXCERPT_MAX] or None
        items.append(
            NewsItem(
                id=item_id(link),
                source_id=result.source.id,
                title=title,
                url=link,
                published=_published(e),
                excerpt=excerpt,
                fetched_at=fetched_at,
            )
        )
    return items, problems
