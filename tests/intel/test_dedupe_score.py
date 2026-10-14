import datetime as dt

from intel.dedupe import Event, dedupe, title_similarity
from intel.score import score_event
from intel.settings import Keyword, Source
from shared.schema import NewsItem

T0 = dt.datetime(2026, 10, 14, 9, tzinfo=dt.UTC)


def item(i, title, url, src="s1", hours=0, excerpt=None):
    return NewsItem(
        id=i,
        source_id=src,
        title=title,
        url=url,
        published=T0 + dt.timedelta(hours=hours),
        excerpt=excerpt,
        fetched_at=T0,
    )


RANK = {"s1": 0, "s2": 1}


def test_url_duplicates_merge_earliest_is_main():
    a = item("a", "新聞甲", "https://x.com/1?utm_source=a", "s2", hours=2)
    b = item("b", "新聞甲（轉載）", "https://x.com/1", "s1", hours=1)
    ev = dedupe([a, b], RANK, None)
    assert len(ev) == 1 and ev[0].main is b and ev[0].others == [a]
    assert ev[0].extra_urls == []  # 正規化後同網址，不重複列
    assert ev[0].source_ids == ["s1", "s2"]


def test_title_similarity_merge_keeps_links():
    a = item(
        "a", "Board issues amendments to climate disclosure standard", "https://x.com/1", hours=0
    )
    b = item(
        "b",
        "Board issues amendments to its climate disclosure standard",
        "https://y.com/9",
        "s2",
        hours=1,
    )
    ev = dedupe([a, b], RANK, 0.85)
    assert len(ev) == 1 and ev[0].extra_urls == ["https://y.com/9"]
    assert len(dedupe([a, b], RANK, None)) == 2  # 門檻未設定就不比對標題


def test_title_similarity_threshold_boundary():
    a = item("a", "abcdefghij", "https://x.com/1")
    b = item("b", "abcdefghik", "https://x.com/2", hours=1)
    sim = title_similarity(a.title, b.title)
    assert len(dedupe([a, b], RANK, sim)) == 1  # 剛好等於門檻 → 合併
    assert len(dedupe([a, b], RANK, sim + 0.001)) == 2


def test_dedupe_order_independent():
    xs = [item(str(i), f"題目{i}", f"https://x.com/{i % 3}", hours=i) for i in range(6)]
    a = [e.member_ids for e in dedupe(xs, RANK, 0.85)]
    b = [e.member_ids for e in dedupe(list(reversed(xs)), RANK, 0.85)]
    assert a == b


KW = [
    Keyword("碳費", "法規與準則", 5, ("carbon fee",)),
    Keyword("白鷺", "客戶", 5),
    Keyword("同業甲", "同業", 3),
    Keyword("淨零", "議題", 2),
]
SRC = {
    "s1": Source("s1", "來源一", "rss", "u", "zh", "同業"),
    "s2": Source("s2", "來源二", "rss", "u", "zh", "其他"),
}


def test_score_sum_synonym_once_case_insensitive():
    ev = Event(item("a", "Carbon Fee 新制", "https://x.com/1", excerpt="碳費 碳費 淨零"))
    sc = score_event(ev, KW, SRC)
    assert sc.score == 7  # 碳費 5（同義詞與重複只算一次）＋淨零 2
    assert sc.matched_terms == ("碳費", "carbon fee", "淨零")
    assert sc.group == "法規與準則"


def test_group_tie_break_priority():
    ev = Event(item("a", "白鷺 碳費", "https://x.com/1"))
    assert score_event(ev, KW, SRC).group == "客戶動態"  # 權重同為 5，客戶優先


def test_group_from_keyword_categories():
    assert score_event(Event(item("a", "同業甲", "https://x.com/1")), KW, SRC).group == "同業動態"
    assert score_event(Event(item("a", "淨零", "https://x.com/1")), KW, SRC).group == "其他"


def test_no_hit_uses_source_category():
    assert (
        score_event(Event(item("a", "無關", "https://x.com/1", "s1")), KW, SRC).group == "同業動態"
    )
    sc = score_event(Event(item("a", "無關", "https://x.com/1", "s2")), KW, SRC)
    assert sc.score == 0 and sc.group == "其他" and sc.matched_terms == ()
