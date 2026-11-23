"""File names follow the handbook rule: 客戶_年度_文件類型_日期, version after the type.

e.g. 明台產險_2026_初稿CH5永續職場_internal_V1_20261111.docx
Versions only ever go up; nothing is ever called final/最新版.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path


def _clean(part: str) -> str:
    return re.sub(r"[\\/:*?\"<>|\s_]+", "", part)


def next_version(out_dir: Path, stem_prefix: str) -> int:
    pattern = re.compile(re.escape(stem_prefix) + r"_V(\d+)_\d{8}")
    versions = [int(m.group(1)) for p in out_dir.glob(f"{stem_prefix}_V*") if (m := pattern.match(p.stem))]
    return max(versions, default=0) + 1


def build_stem(out_dir: Path, client: str, year: str, chapter: str, mode: str,
               today: date | None = None, doc_type: str | None = None) -> str:
    """doc_type replaces the default 「初稿{chapter}」 (e.g. 客戶補件清單); an empty mode adds no suffix."""
    today = today or date.today()
    kind = _clean(doc_type) if doc_type else f"初稿{_clean(chapter)}"
    prefix = f"{_clean(client)}_{_clean(year)}_{kind}" + (f"_{mode}" if mode else "")
    version = next_version(out_dir, prefix)
    return f"{prefix}_V{version}_{today:%Y%m%d}"
