"""抓取 RSS。

- 只支援 RSS；html 來源列為異常（第一版範圍）。
- 網路來源先讀 robots.txt；全部請求合計每秒最多 1 次；逾時 15 秒；不登入。
- 原始內容存到 data/interim/intel/raw/<日期>/<來源id>.xml。
- 離線模式只讀本機檔或快取，完全不連網路。
"""

from __future__ import annotations

import datetime as dt
import time
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
        if source.type != "rss":
            res.error = "第一版只支援 RSS，這個來源是一般網頁，未抓取"
            return res
        try:
            body = self._read(source, res)
        except FetchError as e:
            res.error = str(e)
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
