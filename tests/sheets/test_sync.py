"""階段 4b：同步到 Google 試算表（全部用測試替身，不連網路）。"""

import datetime as dt
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

from digest.pipeline import RunConfig as DigestConfig
from digest.pipeline import run as run_digest
from intel.pipeline import RunConfig as IntelConfig
from intel.pipeline import run as run_intel
from progress.pipeline import RunConfig as ProgressConfig
from progress.pipeline import run as run_progress
from sheets.client import FakeClient, GspreadClient
from sheets.content import SyncError, merge_history, read_sheet_table
from sheets.sync import SyncConfig, sync

ROOT = Path(__file__).resolve().parents[2]
AS_OF = dt.date(2026, 10, 14)
SAMPLE_P = ROOT / "data" / "sample" / "progress"
SAMPLE_F = ROOT / "data" / "sample" / "feeds"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("測試中不允許連網路")

    monkeypatch.setattr(socket, "create_connection", boom)


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    """用假資料實際跑三個系統，產生本機報表。"""
    t = tmp_path_factory.mktemp("w")
    for d in (dt.date(2026, 9, 30), dt.date(2026, 10, 7), AS_OF):
        run_progress(
            ProgressConfig(
                as_of=d,
                input_path=SAMPLE_P / f"項目進度看板_假資料_{d.strftime('%Y%m%d')}.xlsx",
                interim_dir=t / "pi",
                out_dir=t / "progress",
                log_dir=t / "logs",
            )
        )
    run_intel(
        IntelConfig(
            as_of=AS_OF,
            sources_path=SAMPLE_F / "sources_sample.yaml",
            keywords_path=SAMPLE_F / "keywords_sample.yaml",
            interim_dir=t / "ii",
            out_dir=t / "intel",
            offline=True,
            log_dir=t / "logs",
        )
    )
    run_digest(
        DigestConfig(
            as_of=AS_OF,
            out_dir=t / "digest",
            log_dir=t / "logs",
            summary_overrides={
                "progress": t / "progress" / "summary.json",
                "intel": t / "intel" / "summary.json",
            },
        )
    )
    return t


@pytest.fixture
def cfg(outputs, tmp_path):
    c = tmp_path / "config"
    shutil.copytree(ROOT / "config", c)

    def make(client, **kw):
        base = dict(
            as_of=AS_OF,
            config_dir=c,
            digest_dir=outputs / "digest",
            progress_dir=outputs / "progress",
            intel_dir=outputs / "intel",
            client=client,
        )
        base.update(kw)
        return SyncConfig(**base)

    make.config_dir = c
    return make


def test_tabs_written_from_local_reports(cfg, outputs):
    fake = FakeClient()
    titles = sync(cfg(fake))
    assert titles == ["週報", "進度預警", "進度明細", "外部情報", "說明", "指標歷史"]
    for t in titles[:-1]:
        assert fake.tabs[t][0][0].startswith(
            "資料等級：內部一般｜資料截至 2026-10-14｜執行編號 digest-20261014-"
        )
    digest = fake.tabs["週報"]
    flat = [c for r in digest for c in r]
    assert any(str(c).startswith("1. 項目進度看板：本週有 6 案需要注意") for c in flat)
    assert ["紅色預警項目數", "3", "2", "+1", "案"] in digest or [
        "紅色預警項目數",
        3,
        2,
        "+1",
        "案",
    ] in [r[:5] for r in digest]
    # 進度預警＝本機 xlsx 預警清單，逐列相同
    header, rows = read_sheet_table(outputs / "progress" / "進度看板_20261014.xlsx", "預警清單")
    assert fake.tabs["進度預警"][2] == header
    assert [list(map(str, r)) for r in fake.tabs["進度預警"][3:]] == [
        list(map(str, r)) for r in rows
    ]
    intel_header = fake.tabs["外部情報"][2]
    assert intel_header == [
        "首次看到",
        "來源",
        "標題",
        "連結",
        "分類",
        "是否相關",
        "摘要",
        "對優樂地的意義",
        "分數",
    ]
    assert "已讀" not in intel_header and "文章編號" not in intel_header


def test_excluded_fields_never_synced(cfg):
    fake = FakeClient()
    sync(cfg(fake))
    text = " ".join(str(c) for rows in fake.tabs.values() for r in rows for c in r)
    for word in ("不續約", "備註內容", "交初稿", "邀講者"):
        assert word not in text


def test_history_same_week_updates_next_week_appends():
    h = ["週報日期", "紅", "資料等級"]
    a = merge_history([], h, ["2026-10-14", 3, "內部一般"])
    b = merge_history(a, h, ["2026-10-14", 5, "內部一般"])
    assert b == [h, ["2026-10-14", 5, "內部一般"]]
    c = merge_history(b, ["週報日期", "紅", "黃", "資料等級"], ["2026-10-21", 1, 2, "內部一般"])
    assert c[0] == ["週報日期", "紅", "資料等級", "黃"]
    assert c[1] == ["2026-10-14", 5, "內部一般", ""] and c[2] == ["2026-10-21", 1, "內部一般", 2]


def test_rerun_same_week_does_not_duplicate_history(cfg):
    fake = FakeClient()
    sync(cfg(fake))
    sync(cfg(fake))
    rows = fake.tabs["指標歷史"]
    assert len(rows) == 2 and rows[1][0] == "2026-10-14"


def test_user_tabs_untouched(cfg):
    fake = FakeClient({"主管筆記": [["我的筆記"]]})
    sync(cfg(fake))
    assert fake.tabs["主管筆記"] == [["我的筆記"]] and "主管筆記" not in fake.writes


def test_not_configured_is_skipped(cfg, monkeypatch):
    monkeypatch.delenv("MGMT_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(SyncError, match="略過同步"):
        sync(cfg(None))


def test_missing_key_file(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("MGMT_SHEET_ID", "abc")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "nope.json"))
    with pytest.raises(SyncError, match="找不到服務帳號金鑰檔"):
        sync(cfg(None))


@pytest.mark.parametrize(
    "mutate, msg",
    [
        (lambda c: c.update(enabled=False), "enabled 為 false"),
        (lambda c: c.update(enabled="no"), "只能寫 true 或 false"),
        (lambda c: c["tabs"].pop("history"), "tabs 缺少：history"),
        (lambda c: c["tabs"].update(alerts="週報"), "不能重複"),
    ],
)
def test_bad_config(cfg, mutate, msg):
    p = cfg.config_dir / "sheets.yaml"
    c = yaml.safe_load(p.read_text(encoding="utf-8"))
    mutate(c)
    p.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SyncError, match=msg):
        sync(cfg(FakeClient()))


def test_missing_digest_for_date(cfg):
    with pytest.raises(SyncError, match="請先產生週報"):
        sync(cfg(FakeClient(), as_of=AS_OF + dt.timedelta(days=1)))


def test_write_failure_is_plain(cfg):
    class Broken(FakeClient):
        def write(self, title, rows):
            raise ConnectionError("x")

    with pytest.raises(SyncError, match="本機報表不受影響"):
        sync(cfg(Broken()))


def test_missing_progress_report_noted(cfg, tmp_path):
    fake = FakeClient()
    sync(cfg(fake, progress_dir=tmp_path / "none"))
    assert "未更新" in fake.tabs["進度預警"][1][0]


def test_gspread_writes_raw_values():
    calls = {}

    class WS:
        def clear(self):
            calls["clear"] = True

        def update(self, values, range_name, value_input_option):
            calls.update(values=values, range=range_name, opt=value_input_option)

    from gspread.utils import ValueInputOption

    c = object.__new__(GspreadClient)
    c._raw = ValueInputOption.raw
    c._ws = lambda title: WS()
    c.write("x", [["=HYPERLINK(1)", 5, None], ["a"]])
    assert calls["opt"] == ValueInputOption.raw and calls["clear"]
    assert calls["values"] == [["=HYPERLINK(1)", 5, ""], ["a", "", ""]]


def test_no_credentials_in_repo():
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    for f in files:
        p = ROOT / f
        if p.suffix in (".json", ".py", ".yaml", ".md", ".txt", ".toml", ".example"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            assert "BEGIN PRIVATE KEY" not in text and '"private_key"' not in text, f


def test_run_weekly_skip_is_not_failure(monkeypatch, capsys):
    import scripts.run_weekly as weekly
    from scripts import sync_sheets

    monkeypatch.setattr(weekly, "STEPS", [])
    monkeypatch.setattr(weekly, "DIGEST", ("管理層週報", lambda a: 0))
    monkeypatch.setattr(weekly, "SHEETS", ("同步 Google 試算表", lambda a: sync_sheets.SKIPPED))
    assert weekly.main([]) == 0
    monkeypatch.setattr(weekly, "SHEETS", ("同步 Google 試算表", lambda a: 1))
    assert weekly.main([]) == 1
    assert "同步 Google 試算表" in capsys.readouterr().out
