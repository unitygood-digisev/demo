"""網址正規化與文章編號。"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_EXACT = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_EXACT


def normalize_url(url: str) -> str:
    """網址正規化：scheme／網域小寫、去掉 #、去追蹤參數、去結尾斜線、參數排序。"""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    if path == "/":
        path = ""
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    )
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def item_id(url: str) -> str:
    """文章編號＝正規化網址的雜湊前 16 碼。"""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]
