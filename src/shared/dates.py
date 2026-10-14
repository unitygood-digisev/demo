"""日期與金額工具：台灣時區、YYYY-MM-DD、民國年轉換、新台幣格式。"""

from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

TW_TZ = ZoneInfo("Asia/Taipei")
ROC_OFFSET = 1911
MISSING = "待補"

_ISO = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$")
# 民國短格式只接受三位數年份（例如 115/10/14）；兩位數可能是西元或日月年，不猜
_ROC_SHORT = re.compile(r"^\s*(\d{3})[-/.](\d{1,2})[-/.](\d{1,2})\s*$")
_ROC_LONG = re.compile(r"^\s*(?:民國)?\s*(\d{1,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*$")
# 合理年份範圍，超出視為打錯
MIN_YEAR, MAX_YEAR = 1950, 2100


class DateParseError(ValueError):
    """日期無法辨識。"""


def today_tw(
    override: dt.date | str | None = None, *, utc_now: dt.datetime | None = None
) -> dt.date:
    """台灣時區的今天；測試時可傳入固定日期，或傳入 UTC 時間驗證時區換算。"""
    if override is not None:
        return parse_date(override)
    return now_tw(utc_now).date()


def now_tw(utc_now: dt.datetime | None = None) -> dt.datetime:
    if utc_now is not None:
        return utc_now.astimezone(TW_TZ)
    return dt.datetime.now(TW_TZ)


def parse_date(value: object) -> dt.date:
    d = _parse_date(value)
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        raise DateParseError(f"年份不合理（{d.year}）：{value!r}")
    return d


def _parse_date(value: object) -> dt.date:
    """把各種寫法轉成日期。

    接受：date/datetime、YYYY-MM-DD、YYYY/MM/DD、YYYY.MM.DD、民國 115/10/14（三位數年份）、
    民國115年10月14日。年份須在 1950–2100 之間。
    其他寫法一律丟 DateParseError，不猜。
    """
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    # pandas.Timestamp 是 datetime 的子類別，上面已處理
    if not isinstance(value, str):
        raise DateParseError(f"無法辨識的日期：{value!r}")
    for pattern, roc in ((_ISO, False), (_ROC_SHORT, True), (_ROC_LONG, True)):
        m = pattern.match(value)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            if roc:
                if y == 0:
                    raise DateParseError(f"民國沒有 0 年：{value!r}")
                y += ROC_OFFSET
            try:
                return dt.date(y, mo, d)
            except ValueError as e:
                raise DateParseError(f"日期不存在：{value!r}") from e
    raise DateParseError(f"無法辨識的日期：{value!r}")


def fmt_date(value: dt.date | None) -> str:
    """日期輸出一律 YYYY-MM-DD；缺值顯示「待補」。"""
    if value is None:
        return MISSING
    return value.isoformat()


def to_roc(value: dt.date) -> str:
    """西元轉民國，例如 2026-10-14 → 115/10/14。"""
    return f"{value.year - ROC_OFFSET}/{value.month:02d}/{value.day:02d}"


def round_twd(amount: float | int | Decimal) -> int:
    """金額四捨五入到元（不用銀行家捨入）。"""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_twd(amount: float | int | Decimal | None) -> str:
    """新台幣格式，例如 NT$ 1,234（元）；缺值顯示「待補」。"""
    if amount is None:
        return MISSING
    return f"NT$ {round_twd(amount):,}（元）"
