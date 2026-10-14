"""讀取並檢查來源清單、關鍵字清單。設定有問題時列出，不默默略過。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SOURCE_TYPES = ("rss", "html")
GROUPS = ("法規與準則", "同業動態", "客戶動態", "其他")
SOURCE_CATEGORIES = GROUPS + ("同業", "客戶")  # 來源分類也接受簡寫
KEYWORD_CATEGORIES = ("客戶", "同業", "主管機關", "法規與準則", "議題")


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    type: str
    url: str
    lang: str
    category: str


@dataclass(frozen=True)
class Keyword:
    term: str
    category: str
    weight: int
    synonyms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def all_terms(self) -> tuple[str, ...]:
        return (self.term, *self.synonyms)


def _load(path: Path, key: str) -> tuple[list, list[str]]:
    if not path.exists():
        return [], [f"找不到設定檔 {path.name}"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], [f"設定檔 {path.name} 格式錯誤，無法讀取"]
    items = data.get(key)
    if items is None:
        return [], [f"設定檔 {path.name} 缺少「{key}」段落"]
    if not isinstance(items, list):
        return [], [f"設定檔 {path.name} 的「{key}」應為清單"]
    return items, []


def load_sources(path: Path) -> tuple[list[Source], list[str]]:
    raw, problems = _load(path, "sources")
    out: list[Source] = []
    seen: set[str] = set()
    for i, s in enumerate(raw, start=1):
        if not isinstance(s, dict):
            problems.append(f"來源第 {i} 筆格式錯誤")
            continue
        missing = [
            k for k in ("id", "名稱", "類型", "網址", "分類") if not str(s.get(k) or "").strip()
        ]
        if missing:
            problems.append(f"來源第 {i} 筆缺少欄位：{'、'.join(missing)}")
            continue
        sid = str(s["id"]).strip()
        if sid in seen:
            problems.append(f"來源 id「{sid}」重複，只採用第一筆")
            continue
        typ = str(s["類型"]).strip().lower()
        if typ not in SOURCE_TYPES:
            problems.append(f"來源「{sid}」的類型「{s['類型']}」不是 rss 或 html")
            continue
        cat = str(s["分類"]).strip()
        if cat not in SOURCE_CATEGORIES:
            problems.append(f"來源「{sid}」的分類「{cat}」不在允許清單，視為「其他」")
            cat = "其他"
        seen.add(sid)
        out.append(
            Source(
                sid,
                str(s["名稱"]).strip(),
                typ,
                str(s["網址"]).strip(),
                str(s.get("語言") or "").strip(),
                cat,
            )
        )
    return out, problems


def load_keywords(path: Path) -> tuple[list[Keyword], list[str]]:
    raw, problems = _load(path, "keywords")
    out: list[Keyword] = []
    for i, k in enumerate(raw, start=1):
        if not isinstance(k, dict) or not str(k.get("詞") or "").strip():
            problems.append(f"關鍵字第 {i} 筆缺少「詞」")
            continue
        term = str(k["詞"]).strip()
        cat = str(k.get("類別") or "").strip()
        if cat not in KEYWORD_CATEGORIES:
            problems.append(f"關鍵字「{term}」的類別「{cat}」不在允許清單，已略過")
            continue
        w = k.get("權重")
        if isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= 5:
            problems.append(f"關鍵字「{term}」的權重「{w}」應為 1–5 的整數，已略過")
            continue
        syn = k.get("同義詞") or []
        if not isinstance(syn, list):
            syn = [syn]
        out.append(Keyword(term, cat, w, tuple(str(x).strip() for x in syn if str(x).strip())))
    return out, problems
