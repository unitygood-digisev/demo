"""相關度評分與分組。"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from intel.dedupe import Event
from intel.settings import Keyword, Source

# 權重相同時的類別優先順序
CATEGORY_PRIORITY = ("客戶", "同業", "法規與準則", "主管機關", "議題")
CATEGORY_TO_GROUP = {
    "客戶": "客戶動態",
    "同業": "同業動態",
    "法規與準則": "法規與準則",
    "主管機關": "法規與準則",
    "議題": "其他",
}
SOURCE_CATEGORY_TO_GROUP = {"同業": "同業動態", "客戶": "客戶動態"}


@dataclass(frozen=True)
class Scored:
    score: int
    matched_terms: tuple[str, ...]
    matched_keywords: tuple[Keyword, ...]
    group: str


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def score_event(event: Event, keywords: list[Keyword], sources: dict[str, Source]) -> Scored:
    text = _fold(" ".join(f"{m.title}\n{m.excerpt or ''}" for m in event.members))
    hits: list[Keyword] = []
    terms: list[str] = []
    for kw in keywords:
        found = [t for t in kw.all_terms if t and _fold(t) in text]
        if found:
            hits.append(kw)
            terms.extend(t for t in found if t not in terms)
    total = sum(k.weight for k in hits)
    if hits:
        best = min(hits, key=lambda k: (-k.weight, CATEGORY_PRIORITY.index(k.category)))
        group = CATEGORY_TO_GROUP[best.category]
    else:
        src = sources.get(event.main.source_id)
        cat = src.category if src else "其他"
        group = SOURCE_CATEGORY_TO_GROUP.get(cat, cat)
    return Scored(total, tuple(terms), tuple(hits), group)
