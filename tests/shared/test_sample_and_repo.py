"""假資料與倉庫衛生檢查。"""

import subprocess
from pathlib import Path

import feedparser
import yaml

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"


def test_sample_readme_marks_fake():
    assert "假資料" in (SAMPLE / "README.md").read_text(encoding="utf-8")


def test_no_real_board_in_sample():
    """data/sample/ 只能有假資料：系統 1 的看板檔名必須含「假資料」。"""
    for p in (SAMPLE / "progress").glob("*.xlsx"):
        assert "假資料" in p.name, p.name


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


def test_committed_sources_and_keywords_safe():
    """2026-10-15 起來源與關鍵字由使用者提供並提交。提交的版本不能含客戶類關鍵字（只放本機）。"""
    srcs = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    assert srcs and all(str(x["網址"]).startswith("https://") for x in srcs)
    kws = yaml.safe_load((ROOT / "config" / "keywords.yaml").read_text(encoding="utf-8"))
    assert all(k["類別"] != "客戶" for k in kws["keywords"])
    assert "輸出等級" not in kws  # 雲端版不含客戶名稱，維持公開


def test_every_threshold_marked_pending():
    """每個門檻都要標狀態：待主管確認，或「已確認（誰 日期）」。"""
    data = yaml.safe_load((ROOT / "config" / "thresholds.yaml").read_text(encoding="utf-8"))
    for system, items in data.items():
        for key, item in items.items():
            st = item["status"]
            assert st == "待主管確認" or st.startswith("已確認（"), f"{system}.{key}"
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
