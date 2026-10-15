"""讀取並檢查來源清單、關鍵字清單。設定有問題時列出，不默默略過。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SOURCE_TYPES = ("rss", "html")
GROUPS = ("自家品牌", "法規與準則", "政府採購與政策", "同業動態", "客戶動態", "其他")
SOURCE_CATEGORIES = GROUPS + ("同業", "客戶")  # 來源分類也接受簡寫
KEYWORD_CATEGORIES = (
    "自家品牌",
    "客戶",
    "同業",
    "政府採購",
    "政策",
    "主管機關",
    "法規與準則",
    "議題",
)
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


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
    standalone: bool = True  # false：這一組只在同時命中其他關鍵字時才算（例如主管機關名稱）
    restricted_words: tuple[str, ...] = field(default_factory=tuple)  # 不能單獨算的詞（已正規化）

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
        if not _ID.match(sid):
            problems.append(f"來源 id「{sid}」只能用英文字母、數字、底線、連字號，已略過")
            continue
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
    """詞的寫法（全形符號）：「A＋B」＝兩個都要出現；「A／B」＝任一個出現即可。

    檔案最上層可寫「不能單獨算的詞」（例如 ESG、永續、淨零）：這些詞只在同時命中其他關鍵字時才算。
    每一組可寫「單獨不算: true」：整組只在同時命中其他關鍵字時才算。
    """
    raw, problems = _load(path, "keywords")
    restricted: set[str] = set()
    if not problems:
        top = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        lst = top.get("不能單獨算的詞") if isinstance(top, dict) else None
        if lst is not None and not isinstance(lst, list):
            problems.append(f"設定檔 {path.name} 的「不能單獨算的詞」應為清單，已忽略")
        elif lst:
            restricted = {_fold(str(x)) for x in lst if str(x).strip()}
    out: list[Keyword] = []
    used: set[str] = set()
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
        syn = k.get("同義詞")
        if syn is None:
            syn = []
        elif not isinstance(syn, list):
            syn = [syn]
        clean: list[str] = []
        for x in syn:
            if isinstance(x, bool) or not isinstance(x, (str, int, float)) or not str(x).strip():
                problems.append(f"關鍵字「{term}」的同義詞「{x}」不是有效文字，已略過該同義詞")
                continue
            clean.append(str(x).strip())
        if _malformed(term):
            problems.append(f"關鍵字「{term}」的寫法不完整（「＋」或「／」前後要有詞），已略過")
            continue
        for x in [x for x in clean if _malformed(x)]:
            problems.append(
                f"關鍵字「{term}」的同義詞「{x}」寫法不完整（「＋」或「／」前後要有詞），已略過該同義詞"
            )
        clean = [x for x in clean if not _malformed(x)]
        key = _fold(term)
        if key in used:
            problems.append(f"關鍵字「{term}」與前面的關鍵字或同義詞重複，已略過（避免重複計分）")
            continue
        dup_syn = [x for x in clean if _fold(x) in used or _fold(x) == key]
        for x in dup_syn:
            problems.append(f"關鍵字「{term}」的同義詞「{x}」與其他關鍵字重複，已略過該同義詞")
        clean = [x for x in clean if x not in dup_syn]
        used.update({key, *(_fold(x) for x in clean)})
        alone = k.get("單獨不算", False)
        if not isinstance(alone, bool):
            problems.append(f"關鍵字「{term}」的「單獨不算」只能寫 true 或 false，視為 false")
            alone = False
        out.append(
            Keyword(
                term,
                cat,
                w,
                tuple(clean),
                standalone=not alone,
                restricted_words=tuple(sorted(restricted)),
            )
        )
    return out, problems


def _malformed(term: str) -> bool:
    return any(not alt.strip() for part in term.split("＋") for alt in part.split("／"))


def keywords_output_level(path: Path) -> str:
    """關鍵字檔最上層的「輸出等級」：命中詞含客戶名稱時應寫「內部一般」。沒寫時為「公開」。"""
    try:
        top = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return "公開"
    v = top.get("輸出等級") if isinstance(top, dict) else None
    return str(v).strip() if v else "公開"


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()
