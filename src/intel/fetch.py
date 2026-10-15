"""抓取來源。

- 支援 RSS／Atom、新聞 sitemap（news:title + news:publication_date）、WordPress JSON（wp-json）、
  開放資料 JSON（欄位名稱寫在 sources.yaml）。一般網頁（html）沒有發布日期，不抓，列為異常。
- 網路來源先讀 robots.txt；全部請求合計每秒最多 1 次；逾時 15 秒；不登入。
- 原始內容存到 data/interim/intel/raw/<日期>/<來源id>.xml。
- 離線模式只讀本機檔或快取，完全不連網路。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import feedparser

from intel.settings import Source

USER_AGENT = "UnityMgmtSuite-IntelBot/0.1 (internal; contact via company)"
TIMEOUT_SECONDS = 15
HttpGet = Callable[[str], tuple[int, bytes]]


class FetchError(Exception):
    """抓取失敗（訊息為白話中文）。"""


def _requests_get(url: str) -> tuple[int, bytes]:
    import requests

    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
    except requests.Timeout as e:
        raise FetchError("連線逾時") from e
    except requests.RequestException as e:
        raise FetchError("網址無法連線") from e
    return r.status_code, r.content


@dataclass
class FetchResult:
    source: Source
    entries: list = field(default_factory=list)
    error: str | None = None
    warning: str | None = None
    raw_path: Path | None = None


class Fetcher:
    def __init__(
        self,
        root: Path,
        raw_dir: Path,
        as_of: dt.date,
        offline: bool = False,
        http_get: HttpGet | None = None,
        min_interval: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root
        self.day_dir = raw_dir / as_of.strftime("%Y%m%d")
        self.offline = offline
        self.http_get = http_get or _requests_get
        self.min_interval = min_interval
        self.sleep = sleep
        self.clock = clock
        self._last: float | None = None
        self._robots: dict[str, RobotFileParser | None] = {}

    # ---- 網路 ----
    def _get(self, url: str) -> tuple[int, bytes]:
        if self.offline:
            raise FetchError("離線模式不連網路")
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        try:
            return self.http_get(url)
        finally:
            self._last = self.clock()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            status, body = self._get(base + "/robots.txt")
            if status >= 500:
                self._robots[base] = None  # 無法確認，保守視為不允許
            else:
                rp = RobotFileParser()
                rp.parse(
                    body.decode("utf-8", errors="replace").splitlines() if status < 400 else []
                )
                rp.modified()
                self._robots[base] = rp
        rp = self._robots[base]
        return rp is not None and rp.can_fetch(USER_AGENT, url)

    # ---- 主流程 ----
    def fetch(self, source: Source) -> FetchResult:
        res = FetchResult(source)
        if source.type == "html":
            res.error = (
                "一般網頁沒有發布日期，系統不抓；請改找這個網站的 RSS、新聞 sitemap 或開放資料"
            )
            return res
        try:
            body = self._read(source, res)
        except FetchError as e:
            res.error = str(e)
            return res
        if source.type != "rss":
            try:
                res.entries = PARSERS[source.type](body, source)
            except (ValueError, KeyError, TypeError, ET.ParseError) as e:
                res.error = f"內容格式和設定不符，讀不到任何文章（{type(e).__name__}）"
                return res
            if not res.entries:
                res.warning = "沒有讀到任何文章"
            return res
        parsed = feedparser.parse(body)
        if parsed.bozo and not parsed.entries:
            res.error = "RSS 格式壞掉，讀不到任何文章"
        elif parsed.bozo:
            res.warning = "RSS 格式有問題，可能漏掉部分文章"
        res.entries = list(parsed.entries)
        return res

    def _read(self, source: Source, res: FetchResult) -> bytes:
        url = source.url
        if "{api_key}" in url:
            key = os.environ.get(source.key_env, "").strip() if source.key_env else ""
            if not key:
                raise FetchError(f"缺少金鑰（環境變數 {source.key_env or '未設定'}），未抓取")
            url = url.replace("{api_key}", key)
        cache = self.day_dir / f"{source.id}.xml"
        if not url.lower().startswith(("http://", "https://")):
            if "://" in url or url.lower().startswith("file:"):
                raise FetchError("網址只接受 http／https，或專案資料夾內的檔案")
            path = ((self.root / url) if not Path(url).is_absolute() else Path(url)).resolve()
            if not path.is_relative_to(self.root.resolve()):
                raise FetchError("本機檔案只能放在專案資料夾內，未讀取")
            if not path.exists():
                raise FetchError(f"找不到檔案 {path.name}")
            res.raw_path = path
            return path.read_bytes()
        if self.offline:
            if cache.exists():
                res.raw_path = cache
                return cache.read_bytes()
            raise FetchError("離線模式，且今天沒有這個來源的快取")
        if not self._allowed(url):
            raise FetchError("網站的 robots.txt 不允許抓取（或無法確認），未抓取")
        status, body = self._get(url)
        if status >= 400:
            raise FetchError(f"網站回應錯誤（代碼 {status}）")
        self.day_dir.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(body)
        res.raw_path = cache
        return body


# ---- 非 RSS 格式：轉成和 feedparser 一樣的 entry（title、link、summary、published_dt、id） ----
def _parse_dt(v) -> dt.datetime | None:
    """ISO 8601 或「YYYY-MM-DD HH:MM:SS」。沒有時區的當作台灣時間。認不出就回 None（不猜）。"""
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        from shared.dates import TW_TZ

        d = d.replace(tzinfo=TW_TZ)
    return d


_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


def parse_news_sitemap(body: bytes, source: Source) -> list[dict]:
    root = ET.fromstring(body)
    out = []
    for u in root.findall("sm:url", _NS):
        out.append(
            {
                "title": (
                    u.findtext("news:news/news:title", default="", namespaces=_NS) or ""
                ).strip(),
                "link": (u.findtext("sm:loc", default="", namespaces=_NS) or "").strip(),
                "published_dt": _parse_dt(
                    u.findtext("news:news/news:publication_date", default="", namespaces=_NS)
                    or u.findtext("sm:lastmod", default="", namespaces=_NS)
                ),
            }
        )
    return out


def parse_wp_json(body: bytes, source: Source) -> list[dict]:
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("wp-json 應為清單")
    out = []
    for p in data:
        title = p.get("title")
        excerpt = p.get("excerpt")
        out.append(
            {
                "title": title.get("rendered", "") if isinstance(title, dict) else str(title or ""),
                "link": str(p.get("link") or ""),
                "summary": excerpt.get("rendered", "") if isinstance(excerpt, dict) else "",
                "published_dt": _parse_dt(
                    p.get("date_gmt") and p["date_gmt"] + "+00:00" or p.get("date")
                ),
            }
        )
    return out


def parse_json_api(body: bytes, source: Source) -> list[dict]:
    """欄位名稱寫在 sources.yaml 的「欄位」：標題、日期、連結（可省略）、編號、預設連結、清單（可省略）。"""
    f = source.fields
    data = json.loads(body)
    if f.get("清單"):
        for k in str(f["清單"]).split("."):
            data = data[k]
    if not isinstance(data, list):
        raise ValueError("清單不是陣列")
    out = []
    for r in data:
        if not isinstance(r, dict):
            continue
        link = str(r.get(f.get("連結", ""), "") or "").strip() if f.get("連結") else ""
        if not link.lower().startswith(("http://", "https://")):
            link = str(f.get("預設連結") or "")
        out.append(
            {
                "title": str(r.get(f["標題"], "") or ""),
                "link": link,
                "summary": str(r.get(f.get("內文", ""), "") or "") if f.get("內文") else "",
                "published_dt": _parse_dt(r.get(f["日期"])),
                "id": f"{source.id}:{r.get(f['編號'])}" if f.get("編號") else None,
            }
        )
    return out


PARSERS = {"news_sitemap": parse_news_sitemap, "wp_json": parse_wp_json, "json_api": parse_json_api}
