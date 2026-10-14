"""規則單元測試：每條規則含邊界日。"""

import datetime as dt

import pytest

from progress.board import Board, BoardConfig
from progress.rules import evaluate, owners_of

CFG = BoardConfig.load()
TH = {
    "P02_due_soon_days": 7,
    "P04_unchanged_days": 14,
    "P05_max_active_projects": 5,
    "board_stale_days": 7,
}
TODAY = dt.date(2026, 10, 14)


def row(i, name, stage="進行中", owner="甲", d=None, step="x"):
    return {
        "_row": i,
        "案子": name,
        "類別": None,
        "階段": stage,
        "負責人": owner,
        "下一步": step,
        "下一個日期": d,
    }


def ev_of(rows, since=None, th=TH, history_ok=True):
    return evaluate(Board(None, rows), TODAY, CFG, th, since or {}, history_ok)


def rules(ev, name):
    return sorted(a.rule for a in ev.alerts if a.subject == name)


@pytest.mark.parametrize(
    "days, expected",
    [(-30, ["P01"]), (-1, ["P01"]), (0, ["P02"]), (6, ["P02"]), (7, ["P02"]), (8, []), (60, [])],
)
def test_p01_p02_boundaries(days, expected):
    ev = ev_of([row(5, "A", d=TODAY + dt.timedelta(days=days))])
    assert rules(ev, "A") == expected


@pytest.mark.parametrize("stage", ["規劃中", "洽談中", "進行中", "卡關", "結案中", "暫緩"])
def test_overdue_applies_to_every_stage_except_done(stage):
    assert "P01" in rules(ev_of([row(5, "A", stage=stage, d=TODAY - dt.timedelta(days=1))]), "A")


def test_done_never_alerts():
    ev = ev_of([row(5, "A", stage="已完成", d=TODAY - dt.timedelta(days=3))])
    assert ev.alerts == [] and ev.lights[5] == "綠"


def test_p03_blocked_and_light_is_worst():
    ev = ev_of([row(5, "A", stage="卡關", d=TODAY + dt.timedelta(days=3))])
    assert rules(ev, "A") == ["P02", "P03"] and ev.lights[5] == "紅"
    a = next(a for a in ev.alerts if a.rule == "P03")
    assert a.level == "紅" and "卡關" in a.why and a.suggested_owner == "甲"


@pytest.mark.parametrize("since_days, expected", [(14, ["P04"]), (15, ["P04"]), (13, [])])
def test_p04_boundary(since_days, expected):
    ev = ev_of(
        [row(5, "A", d=TODAY + dt.timedelta(days=30))],
        since={"A": TODAY - dt.timedelta(days=since_days)},
    )
    assert rules(ev, "A") == expected


def test_p04_only_active_and_notes_when_history_short():
    since = {"A": TODAY - dt.timedelta(days=30), "B": TODAY - dt.timedelta(days=30)}
    ev = ev_of([row(5, "A", stage="洽談中"), row(6, "B")], since=since, history_ok=False)
    assert rules(ev, "A") == [] and rules(ev, "B") == ["P04"]
    assert any("快照不足" in n for n in ev.notes)


@pytest.mark.parametrize("n, expected", [(5, False), (6, True)])
def test_p05_boundary_and_wording(n, expected):
    rows = [row(i, f"案{i}", owner="甲") for i in range(n)]
    ev = ev_of(rows)
    hit = [a for a in ev.alerts if a.rule == "P05"]
    assert bool(hit) is expected
    if hit:
        assert hit[0].subject == "甲" and "不是績效評估" in hit[0].suggested_owner
    assert ev.owner_counts["甲"] == [f"案{i}" for i in range(n)]


def test_p05_counts_only_active():
    rows = [row(i, f"案{i}", stage="洽談中") for i in range(10)]
    assert ev_of(rows).owner_counts == {}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("甲", ["甲"]),
        ("甲（與乙）", ["甲"]),
        ("甲（乙 規劃）", ["甲"]),
        ("甲、乙", ["甲", "乙"]),
        ("甲／乙／丙", ["甲", "乙", "丙"]),
        ("甲(乙)/丙", ["甲", "丙"]),
        ("行政", []),
        ("全體專案人員", []),
        ("", []),
        (None, []),
    ],
)
def test_owner_parsing(text, expected):
    assert owners_of(text, CFG) == expected


def test_quality_missing_date_and_owner_only_for_active():
    ev = ev_of(
        [row(5, "A", d=None), row(6, "B", stage="洽談中", d=None), row(7, "C", owner=None, d=TODAY)]
    )
    got = {(q.project, q.field) for q in ev.quality}
    assert got == {("A", "下一個日期"), ("C", "負責人")}


def test_thresholds_none_disable_rules():
    th = {
        "P02_due_soon_days": None,
        "P04_unchanged_days": None,
        "P05_max_active_projects": None,
        "board_stale_days": None,
    }
    rows = [row(i, f"案{i}", d=TODAY) for i in range(8)]
    ev = ev_of(rows, since={"案0": TODAY - dt.timedelta(days=99)}, th=th)
    assert ev.alerts == []
    assert any("P04 門檻未設定" in n for n in ev.notes)


def test_no_ranking_words_and_owners_sorted():
    rows = [row(i, f"案{i}", owner=o) for i, o in enumerate(["丙", "甲", "乙", "甲"])]
    ev = ev_of(rows)
    assert list(ev.owner_counts) == sorted(ev.owner_counts)
    text = " ".join(a.why + a.suggested_owner for a in ev.alerts)
    for w in ("排名", "第一名", "最差", "表現", "績效不佳"):
        assert w not in text
