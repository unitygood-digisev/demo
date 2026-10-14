from intel.settings import load_keywords, load_sources
from intel.urls import item_id, normalize_url

from .conftest import SAMPLE


def test_normalize_url_variants_equal():
    base = "https://example.com/news/1002"
    for v in [
        "https://EXAMPLE.com/news/1002",
        "https://example.com/news/1002/",
        "https://example.com/news/1002?utm_source=rss",
        "https://example.com/news/1002?utm_source=a&utm_medium=b#top",
        "https://example.com/news/1002?fbclid=xyz",
        "HTTPS://example.com/news/1002?gclid=1",
    ]:
        assert normalize_url(v) == normalize_url(base), v
        assert item_id(v) == item_id(base)


def test_normalize_keeps_real_params_sorted():
    assert normalize_url("https://a.com/x?b=2&a=1&utm_x=9") == "https://a.com/x?a=1&b=2"
    assert item_id("https://a.com/x?id=1") != item_id("https://a.com/x?id=2")
    assert item_id("https://a.com/x") != item_id("https://a.com/y")


def test_sample_settings_load_clean():
    s, p = load_sources(SAMPLE / "sources_sample.yaml")
    assert p == [] and [x.id for x in s] == [
        "fake_agency_zh",
        "fake_board_en",
        "fake_broken",
        "fake_missing",
    ]
    k, p = load_keywords(SAMPLE / "keywords_sample.yaml")
    assert p == [] and len(k) == 5


def test_bad_sources_listed(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(
        """sources:
  - {id: a, 名稱: A, 類型: rss, 網址: x.xml, 分類: 其他}
  - {id: a, 名稱: A2, 類型: rss, 網址: y.xml, 分類: 其他}
  - {id: b, 名稱: B, 類型: rss, 分類: 其他}
  - {id: c, 名稱: C, 類型: pdf, 網址: z, 分類: 其他}
  - {id: d, 名稱: D, 類型: RSS, 網址: d.xml, 分類: 奇怪}
  - 純文字
""",
        encoding="utf-8",
    )
    s, p = load_sources(f)
    assert [x.id for x in s] == ["a", "d"]
    assert s[1].category == "其他" and s[1].type == "rss"
    assert len(p) == 5


def test_bad_keywords_listed(tmp_path):
    f = tmp_path / "k.yaml"
    f.write_text(
        """keywords:
  - {詞: 碳費, 類別: 法規與準則, 權重: 5, 同義詞: [carbon fee]}
  - {詞: 甲, 類別: 亂寫, 權重: 3}
  - {詞: 乙, 類別: 議題, 權重: 9}
  - {詞: 丙, 類別: 議題, 權重: "3"}
  - {類別: 議題, 權重: 3}
  - {詞: 丁, 類別: 議題, 權重: 2, 同義詞: 單一字串}
""",
        encoding="utf-8",
    )
    k, p = load_keywords(f)
    assert [x.term for x in k] == ["碳費", "丁"]
    assert k[1].synonyms == ("單一字串",)
    assert len(p) == 4


def test_missing_or_empty_settings(tmp_path):
    s, p = load_sources(tmp_path / "none.yaml")
    assert s == [] and "找不到" in p[0]
    f = tmp_path / "e.yaml"
    f.write_text("", encoding="utf-8")
    s, p = load_sources(f)
    assert s == [] and p
    f.write_text("sources: [", encoding="utf-8")
    assert "格式錯誤" in load_sources(f)[1][0]
