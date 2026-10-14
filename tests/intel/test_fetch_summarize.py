import datetime as dt
import json

import pytest

from intel.dedupe import Event
from intel.fetch import Fetcher, FetchError
from intel.settings import Source
from intel.summarize import FAILED, LINK_FLAG, TITLE_ONLY, Summarizer, parse_response
from shared.llm_client import LLMClient, LLMPolicyError
from shared.schema import NewsItem

from .conftest import AS_OF, ROOT, SAMPLE

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>A</title><link>https://ex.com/a</link><description>d</description></item></channel></rss>"""


def src(url, typ="rss", sid="s"):
    return Source(sid, "來源", typ, url, "zh", "其他")


def fetcher(tmp_path, http=None, offline=False, sleeps=None, clock=None):
    return Fetcher(
        ROOT,
        tmp_path / "raw",
        AS_OF,
        offline,
        http,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=clock or (lambda: 0.0),
    )


def test_local_sample_ok(tmp_path):
    r = fetcher(tmp_path).fetch(src(str(SAMPLE / "fake_zh.xml")))
    assert r.error is None and len(r.entries) == 5


@pytest.mark.parametrize(
    "source, expect",
    [
        (src("data/sample/feeds/broken.xml"), "格式壞掉"),
        (src("data/sample/feeds/nope.xml"), "找不到檔案"),
        (src("https://ex.com/page", "html"), "只支援 RSS"),
    ],
)
def test_failures_reported(tmp_path, source, expect):
    r = fetcher(tmp_path).fetch(source)
    assert r.error and expect in r.error and r.entries == []


def test_bozo_with_entries_is_warning(tmp_path):
    p = tmp_path / "half.xml"
    p.write_bytes(RSS.replace(b"</channel></rss>", b"<item><title>B"))
    f = Fetcher(tmp_path, tmp_path / "raw", AS_OF, sleep=lambda s: None)
    r = f.fetch(src(str(p)))
    assert r.error is None and r.warning and len(r.entries) >= 1


def test_offline_http_without_cache_does_not_connect(tmp_path):
    def never(url):
        raise AssertionError("不應連線")

    r = fetcher(tmp_path, http=never, offline=True).fetch(src("https://ex.com/feed"))
    assert "離線模式" in r.error


def test_offline_http_uses_cache(tmp_path):
    day = tmp_path / "raw" / "20261014"
    day.mkdir(parents=True)
    (day / "s.xml").write_bytes(RSS)
    r = fetcher(tmp_path, offline=True).fetch(src("https://ex.com/feed"))
    assert r.error is None and len(r.entries) == 1


def _http(table):
    calls = []

    def get(url):
        calls.append(url)
        return table[url]

    return get, calls


def test_robots_disallow(tmp_path):
    get, calls = _http({"https://ex.com/robots.txt": (200, b"User-agent: *\nDisallow: /")})
    r = fetcher(tmp_path, http=get).fetch(src("https://ex.com/feed"))
    assert "robots.txt" in r.error and calls == ["https://ex.com/robots.txt"]


def test_robots_server_error_is_conservative(tmp_path):
    get, calls = _http({"https://ex.com/robots.txt": (503, b"")})
    r = fetcher(tmp_path, http=get).fetch(src("https://ex.com/feed"))
    assert "robots.txt" in r.error and len(calls) == 1


def test_robots_missing_allows_and_caches_and_rate_limits(tmp_path):
    t = [0.0]
    get, calls = _http({"https://ex.com/robots.txt": (404, b""), "https://ex.com/feed": (200, RSS)})
    sleeps = []
    r = fetcher(tmp_path, http=get, sleeps=sleeps, clock=lambda: t[0]).fetch(
        src("https://ex.com/feed")
    )
    assert r.error is None and len(r.entries) == 1
    assert calls == ["https://ex.com/robots.txt", "https://ex.com/feed"]
    assert sleeps == [1.0]  # 兩次請求間至少隔 1 秒
    assert (tmp_path / "raw" / "20261014" / "s.xml").read_bytes() == RSS


@pytest.mark.parametrize(
    "url", ["/etc/passwd", "../../../../etc/hosts", "file:///etc/passwd", "ftp://x/feed"]
)
def test_local_paths_outside_project_rejected(tmp_path, url):
    r = fetcher(tmp_path).fetch(src(url))
    assert r.error and r.raw_path is None and r.entries == []


def test_http_error_and_connection_error(tmp_path):
    get, _ = _http({"https://ex.com/robots.txt": (404, b""), "https://ex.com/feed": (500, b"")})
    assert "代碼 500" in fetcher(tmp_path, http=get).fetch(src("https://ex.com/feed")).error

    def down(url):
        raise FetchError("網址無法連線")

    assert fetcher(tmp_path, http=down).fetch(src("https://ex.com/feed")).error == "網址無法連線"


# ---- 摘要 ----
T0 = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)


def ev(excerpt):
    return Event(
        NewsItem(
            id="a",
            source_id="s",
            title="標題",
            url="https://ex.com/a",
            excerpt=excerpt,
            fetched_at=T0,
        )
    )


class Spy(LLMClient):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.levels = []

    def complete(self, **kw):
        self.levels.append(kw["level"])
        return super().complete(**kw)


def summarizer(tmp_path, reply):
    c = Spy(
        cache_dir=tmp_path / "c", log_path=tmp_path / "l.jsonl", mock_responder=lambda p, t: reply
    )
    return Summarizer(c, ROOT / "prompts" / "intel_summary.md"), c


def test_title_only_does_not_call_model(tmp_path):
    s, c = summarizer(tmp_path, "{}")
    out = s.summarize(ev(None))
    assert out.summary == TITLE_ONLY and out.status == "title_only" and c.levels == []
    assert s.summarize(ev("   ")).status == "title_only"


def test_model_called_only_with_public_level(tmp_path):
    s, c = summarizer(tmp_path, json.dumps({"摘要": "一句。兩句。", "意義": "有關。"}))
    out = s.summarize(ev("內文"))
    assert out.status == "ok" and out.mock and c.levels == ["公開"]
    assert s.version == "intel_summary-v1"


@pytest.mark.parametrize("level", ["內部一般", "內部敏感", "客戶機密", "未知"])
def test_intel_purpose_rejects_other_levels(tmp_path, level):
    c = LLMClient(cache_dir=tmp_path / "c", log_path=tmp_path / "l.jsonl")
    with pytest.raises(LLMPolicyError):
        c.complete(
            level=level, purpose="intel_summary", prompt_version="v1", prompt="p", input_text="x"
        )


@pytest.mark.parametrize(
    "reply", ["不是 JSON", "[1, 2]", '{"摘要": ""}', '{"意義": "x"}', '{"摘要": 1, "意義": "x"}']
)
def test_bad_model_reply_fails_loudly(reply):
    out = parse_response(reply)
    assert out.status == "failed" and out.summary == FAILED and out.flags


def test_reply_with_fence_ok():
    out = parse_response('```json\n{"摘要": "一句。", "意義": "有關。"}\n```')
    assert out.status == "ok" and out.summary == "一句。"


@pytest.mark.parametrize(
    "bad",
    [
        "見 https://evil.example/x 詳情。",
        "參考 www.evil.example",
        "[這裡](javascript:alert(1))",
        "[原文](http://x)",
        "寄信 mailto:a@evil.example",
        "聯絡 a@b.example",
        "ftp://x/y",
        "ｈｔｔｐｓ：／／ｅｖｉｌ．ｅｘａｍｐｌｅ",
        "HTTPS://EVIL.EXAMPLE",
        "<a href='http://x'>點</a>",
    ],
)
def test_any_link_in_reply_discards_whole_summary(bad):
    for reply in ({"摘要": bad, "意義": "有關。"}, {"摘要": "正常。", "意義": bad}):
        out = parse_response(json.dumps(reply, ensure_ascii=False))
        assert out.status == "failed" and out.summary == FAILED and out.flags == [LINK_FLAG]


@pytest.mark.parametrize(
    "ok",
    [
        "依 ISO 14064-1 與 IFRS S2:2023 揭露。",
        "溫升 1.5°C 目標。",
        "Scope 3 category 15 relief.",
        "金管會發布新制。",
        "The new data: emissions fell.",
        "See the file: guidance.",
        "S2 [draft] (2026) 公布。",
        "Amazon.com 宣布減碳。",
        "TSMC.tw 與 ESG.ai 平台。",
    ],
)
def test_normal_text_not_mistaken_for_link(ok):
    assert (
        parse_response(json.dumps({"摘要": ok, "意義": "有關。"}, ensure_ascii=False)).status
        == "ok"
    )


def test_newlines_collapsed():
    out = parse_response(json.dumps({"摘要": "一句。\n\n## 偽造標題\n- 項目", "意義": "有\n關"}))
    assert "\n" not in out.summary and "\n" not in out.meaning


def test_length_and_sentence_flags():
    out = parse_response(json.dumps({"摘要": "長" * 81, "意義": "短"}))
    assert any("超過 80 字" in f for f in out.flags)
    out = parse_response(json.dumps({"摘要": "一。二。三。", "意義": "意" * 41}))
    assert any("超過兩句" in f for f in out.flags) and any("超過 40 字" in f for f in out.flags)
    out = parse_response(json.dumps({"摘要": "長" * 80, "意義": "意" * 40}))
    assert out.flags == []
