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
    if entry.get("published_dt"):
        return entry["published_dt"].astimezone(TW_TZ)
    raw = str(entry.get("published") or entry.get("updated") or "")
    if raw.rstrip().endswith(" CST"):
        # 台灣政府網站常把台灣時間寫成「CST」，會被當成美國中部時間，改成 +08:00
        import email.utils

        parsed = email.utils.parsedate_tz(raw.rstrip()[:-4] + " +0800")
        if parsed:
            return dt.datetime.fromtimestamp(email.utils.mktime_tz(parsed), dt.UTC).astimezone(
                TW_TZ
            )
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(st), dt.UTC).astimezone(TW_TZ)


def to_items(result: FetchResult, fetched_at: dt.datetime) -> tuple[list[NewsItem], list[str]]:
    """回傳 (文章, 問題清單)。沒有標題或網址的文章列為問題，不默默丟掉。"""
    items: list[NewsItem] = []
    problems: list[str] = []
    bad: list[int] = []
    for i, e in enumerate(result.entries, start=1):
        title = clean_text(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link.lower().startswith(("http://", "https://")):
            bad.append(i)
            continue
        excerpt = clean_text(e.get("summary") or e.get("description"))[:EXCERPT_MAX] or None
        items.append(
            NewsItem(
                id=item_id(e["id"]) if e.get("id") else item_id(link),
                source_id=result.source.id,
                title=title,
                url=link,
                published=_published(e),
                excerpt=excerpt,
                fetched_at=fetched_at,
            )
        )
    if bad:
        # 合成一句，避免整份來源壞掉時洗版
        nums = "、".join(str(i) for i in bad[:5]) + ("…" if len(bad) > 5 else "")
        problems.append(
            f"{result.source.name} 有 {len(bad)} 則缺少標題或有效網址（第 {nums} 則），未納入"
        )
    return items, problems
