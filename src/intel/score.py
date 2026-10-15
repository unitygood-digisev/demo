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


def term_hit(term: str, text: str, restricted: tuple[str, ...] = ()) -> str | None:
    """回傳 strong（不靠限制詞就成立）、weak（要靠 ESG／永續／淨零這類限制詞才成立）或 None。

    「A＋B」兩段都要出現（只認全形＋）；每段裡「A／B」任一個出現即可。text 須已經過 _fold。
    """
    parts = [p for p in term.split("＋") if p.strip()]
    if not parts:
        return None
    strong = False  # 至少有一段是靠非限制詞命中，才算可以單獨成立
    for part in parts:
        alts = [_fold(a.strip()) for a in part.split("／") if a.strip()]
        hit = [a for a in alts if _alt_hit(a, text)]
        if not hit:
            return None
        if any(a not in restricted for a in hit):
            strong = True
    return "strong" if strong else "weak"


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
        kinds = {t: term_hit(t, text, kw.restricted_words) for t in kw.all_terms if t}
        found = [t for t, k in kinds.items() if k]
        if not found:
            continue
        found_by[kw] = found
        if kw.standalone and any(k == "strong" for k in kinds.values()):
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
