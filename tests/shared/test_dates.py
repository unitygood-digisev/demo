import datetime as dt

import pandas as pd
import pytest

from shared.dates import (
    DateParseError,
    fmt_date,
    fmt_twd,
    parse_date,
    round_twd,
    to_roc,
    today_tw,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-10-14", dt.date(2026, 10, 14)),
        ("2026/1/5", dt.date(2026, 1, 5)),
        ("115/10/14", dt.date(2026, 10, 14)),
        ("99/01/01", dt.date(2010, 1, 1)),
        ("民國115年10月14日", dt.date(2026, 10, 14)),
        ("115年1月2日", dt.date(2026, 1, 2)),
        (dt.datetime(2026, 10, 14, 23, 59), dt.date(2026, 10, 14)),
        (pd.Timestamp("2026-10-14"), dt.date(2026, 10, 14)),
        (dt.date(2026, 2, 28), dt.date(2026, 2, 28)),
    ],
)
def test_parse_date_ok(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw", ["2026-13-40", "2026/02/30", "115/02/30", "14/10/2026", "下週一", "", 20261014, None]
)
def test_parse_date_rejects(raw):
    with pytest.raises(DateParseError):
        parse_date(raw)


def test_today_override_and_timezone():
    assert today_tw("2026-10-14") == dt.date(2026, 10, 14)
    assert isinstance(today_tw(), dt.date)


def test_roc_and_format():
    assert to_roc(dt.date(2026, 10, 14)) == "115/10/14"
    assert fmt_date(dt.date(2026, 1, 2)) == "2026-01-02"
    assert fmt_date(None) == "待補"


def test_twd_rounding_half_up():
    assert round_twd(2.5) == 3
    assert round_twd(1234.49) == 1234
    assert fmt_twd(1234567.5) == "NT$ 1,234,568（元）"
    assert fmt_twd(None) == "待補"
