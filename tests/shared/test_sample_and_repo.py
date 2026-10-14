"""假資料與倉庫衛生檢查。"""

import subprocess
from pathlib import Path

import feedparser
import yaml

from scripts.check_inputs import PROGRESS_SPECS, check_dir

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"


def test_sample_progress_has_the_three_planted_errors():
    results = check_dir(SAMPLE / "progress", PROGRESS_SPECS)
    got = {
        (f, i.row, i.column, i.problem.split("（")[0]) for f, r in results.items() for i in r.issues
    }
    assert ("projects.xlsx", 11, "負責人", "必填欄位空白") in got
    assert ("projects.xlsx", 4, "project_id", "重複的 ID") in got
    assert ("projects.xlsx", 12, "project_id", "重複的 ID") in got
    assert ("projects.xlsx", 13, "預計結案日", "日期錯誤") in got
    assert ("milestones.xlsx", 14, "預計日", "日期錯誤") in got
    assert len(got) == 5
    assert results["updates.xlsx"].ok


def test_sample_is_marked_fake():
    assert "假資料" in (SAMPLE / "README.md").read_text(encoding="utf-8")
    results = check_dir(SAMPLE / "progress", PROGRESS_SPECS)
    clients = results["projects.xlsx"].data["客戶"].dropna()
    assert all(c.startswith("（假資料）") for c in clients)


def test_sample_feeds():
    zh = feedparser.parse(SAMPLE / "feeds" / "fake_zh.xml")
    en = feedparser.parse(SAMPLE / "feeds" / "fake_en.xml")
    broken = feedparser.parse(SAMPLE / "feeds" / "broken.xml")
    assert not zh.bozo and len(zh.entries) == 5
    assert not en.bozo and len(en.entries) == 5
    assert broken.bozo
    for e in zh.entries + en.entries:
        assert e.link.startswith(
            ("https://example.com/", "https://example.org/", "https://example.net/")
        )


def test_config_sources_and_keywords_are_empty_templates():
    assert (
        yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
        == []
    )
    assert (
        yaml.safe_load((ROOT / "config" / "keywords.yaml").read_text(encoding="utf-8"))["keywords"]
        == []
    )


def test_every_threshold_marked_pending():
    data = yaml.safe_load((ROOT / "config" / "thresholds.yaml").read_text(encoding="utf-8"))
    for system, items in data.items():
        for key, item in items.items():
            assert item["status"] == "待主管確認", f"{system}.{key}"
            assert "value" in item and item.get("說明"), f"{system}.{key}"


def test_gitignore_covers_sensitive_paths():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for needed in ["data/raw/*", "data/interim/*", "data/out/*", ".env", "logs/*"]:
        assert needed in gi


def test_no_secrets_or_raw_data_tracked():
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [
        f
        for f in files
        if f == ".env"
        or (
            f.startswith(("data/raw/", "data/interim/", "data/out/", "logs/"))
            and not f.endswith(".gitkeep")
        )
    ]
    assert bad == []
