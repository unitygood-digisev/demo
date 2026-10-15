"""相關度評分與分組。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from intel.dedupe import Event
from intel.settings import Keyword, Source

# 權重相同時的類別優先順序
CATEGORY_PRIORITY = (
    "自家品牌",
    "客戶",
    "同業",
    "政府採購",
    "法規與準則",
    "政策",
    "主管機關",
    "議題",
)
CATEGORY_TO_GROUP = {
    "自家品牌": "自家品牌",
    "政府採購": "政府採購與政策",
    "政策": "政府採購與政策",
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
    importance: int = 0  # 命中關鍵字中最高的重要程度（權重）


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def term_hit(term: str, text: str) -> bool:
    """「A＋B」兩個都要出現；每一段裡「A／B」任一個出現即可。text 須已經過 _fold。"""
    parts = [p for p in re.split(r"[＋+]", term) if p.strip()]
    return bool(parts) and all(
        any(_alt_hit(_fold(alt.strip()), text) for alt in part.split("／") if alt.strip())
        for part in parts
    )


def _alt_hit(alt: str, text: str) -> bool:
    # 短的英文縮寫（例如 BV、CU、SGS）要前後不是英數字，避免對到 obviously、customer
    if len(alt) <= 4 and re.fullmatch(r"[0-9a-zà-ÿ&]+", alt):
        return re.search(rf"(?<![0-9a-z]){re.escape(alt)}(?![0-9a-z])", text) is not None
    return alt in text


def score_event(event: Event, keywords: list[Keyword], sources: dict[str, Source]) -> Scored:
    text = _fold(" ".join(f"{m.title}\n{m.excerpt or ''}" for m in event.members))
    strong: list[Keyword] = []  # 可以單獨成立的命中
    weak: list[Keyword] = []  # 要有其他命中才算
    terms: list[str] = []
    found_by: dict[Keyword, list[str]] = {}
    for kw in keywords:
        found = [t for t in kw.all_terms if t and term_hit(t, text)]
        if not found:
            continue
        found_by[kw] = found
        if kw.standalone and any(t not in kw.restricted for t in found):
            strong.append(kw)
        else:
            weak.append(kw)
    hits = strong + weak if strong else []
    for kw in hits:
        terms.extend(t for t in found_by[kw] if t not in terms)
    total = sum(k.weight for k in hits)
    if hits:
        best = min(hits, key=lambda k: (-k.weight, CATEGORY_PRIORITY.index(k.category)))
        group = CATEGORY_TO_GROUP[best.category]
    else:
        src = sources.get(event.main.source_id)
        cat = src.category if src else "其他"
        group = SOURCE_CATEGORY_TO_GROUP.get(cat, cat)
    return Scored(total, tuple(terms), tuple(hits), group, max((k.weight for k in hits), default=0))
