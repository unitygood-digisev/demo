"""階段 1b：副執行長每日新聞推送（關鍵字組合、郵件內容、寄信限制）。全部離線、不真的寄信。"""

import datetime as dt
import json
import subprocess

import pytest

from intel.dedupe import Event
from intel.score import score_event
from intel.settings import load_keywords
from shared.mail_client import MailClient, MailError, MailNotConfigured
from shared.schema import NewsItem

from .conftest import AS_OF, ROOT, SAMPLE

T0 = dt.datetime(2026, 10, 14, 9, tzinfo=dt.UTC)


def ev(title, excerpt=""):
    return Event(
        NewsItem(
            id="a",
            source_id="s1",
            title=title,
            url="https://x.example/1",
            published=T0,
            excerpt=excerpt,
            fetched_at=T0,
        ),
        [],
    )


def kws(tmp_path, body):
    p = tmp_path / "k.yaml"
    p.write_text(body, encoding="utf-8")
    out, problems = load_keywords(p)
    assert problems == []
    return out


RULES = """
不能單獨算的詞: [ESG, 永續, 淨零]
keywords:
  - 詞: 永續＋勞務採購
    類別: 政府採購
    權重: 5
    同義詞: [中小企業＋碳盤查／減碳補助]
  - 詞: 淨零
    類別: 議題
    權重: 3
    同義詞: [SBTi]
  - 詞: 環境部
    類別: 主管機關
    權重: 2
    單獨不算: true
  - 詞: 甲品牌
    類別: 自家品牌
    權重: 5
  - 詞: 範疇三／Scope 3
    類別: 法規與準則
    權重: 5
"""


@pytest.mark.parametrize(
    "title, score",
    [
        ("某機關公告永續勞務採購案", 5),  # 兩個詞都出現
        ("勞務採購公告", 0),  # 只有一個
        ("中小企業減碳補助開跑", 5),  # 「／」任一即可
        ("中小企業新聞", 0),
        ("企業淨零轉型", 0),  # 淨零不能單獨算
        ("企業淨零轉型，SBTi 目標", 3),  # 同一組有其他詞：算一次
        ("淨零與甲品牌", 8),  # 有其他關鍵字時，淨零可以算
        ("環境部公告", 0),  # 單獨不算的組
        ("環境部公告範疇三指引", 7),
        ("Scope 3 新規", 5),
    ],
)
def test_combo_and_restricted_terms(tmp_path, title, score):
    sc = score_event(ev(title), kws(tmp_path, RULES), {})
    assert sc.score == score


def test_new_categories_and_groups(tmp_path):
    sc = score_event(ev("甲品牌獲獎"), kws(tmp_path, RULES), {})
    assert sc.group == "自家品牌"
    sc = score_event(ev("永續勞務採購"), kws(tmp_path, RULES), {})
    assert sc.group == "政府採購與政策"


def test_importance_is_max_weight(tmp_path):
    sc = score_event(ev("環境部公告範疇三指引"), kws(tmp_path, RULES), {})
    assert sc.importance == 5


def test_restricted_list_must_be_list(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("不能單獨算的詞: ESG\nkeywords: []\n", encoding="utf-8")
    _, problems = load_keywords(p)
    assert any("不能單獨算的詞" in x for x in problems)


# ---- 寄信 ----
class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, pw):
        assert pw == "app-pass"

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def mail_env(monkeypatch, tmp_path):
    FakeSMTP.sent = []
    monkeypatch.setenv("MAIL_FROM", "sender@unitygood.com")
    monkeypatch.setenv("MAIL_APP_PASSWORD", "app-pass")
    monkeypatch.setenv("MAIL_TO", "boss@unitygood.com")
    return tmp_path


def client(tmp_path, config_dir, **kw):
    return MailClient(
        config_dir=config_dir,
        log_path=tmp_path / "sent.jsonl",
        smtp_factory=FakeSMTP,
        env_file=tmp_path / "no.env",
        **kw,
    )


def test_mail_sends_to_whitelist_once_per_day(mail_env, config_dir):
    c = client(mail_env, config_dir)
    assert c.send("日報", "內容", level="內部一般", kind="intel_daily", day=AS_OF) is True
    assert len(FakeSMTP.sent) == 1 and FakeSMTP.sent[0]["To"] == "boss@unitygood.com"
    assert c.send("日報", "內容", level="內部一般", kind="intel_daily", day=AS_OF) is False
    assert len(FakeSMTP.sent) == 1  # 同一天不重寄
    rec = json.loads((mail_env / "sent.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["day"] == "2026-10-14" and "內容" not in json.dumps(rec, ensure_ascii=False)


@pytest.mark.parametrize(
    "to", ["someone@gmail.com", "boss@unitygood.com.evil.com", "a@x.com,boss@unitygood.com"]
)
def test_mail_refuses_outside_domain(mail_env, config_dir, monkeypatch, to):
    monkeypatch.setenv("MAIL_TO", to)
    with pytest.raises(MailError, match="公司信箱"):
        client(mail_env, config_dir).send("日報", "x", level="公開", kind="intel_daily", day=AS_OF)
    assert FakeSMTP.sent == []


@pytest.mark.parametrize("level", ["內部敏感", "客戶機密", "亂寫"])
def test_mail_refuses_high_level(mail_env, config_dir, level):
    with pytest.raises(MailError, match="資料等級"):
        client(mail_env, config_dir).send("日報", "x", level=level, kind="intel_daily", day=AS_OF)
    assert FakeSMTP.sent == []


def test_mail_not_configured(monkeypatch, tmp_path, config_dir):
    for k in ("MAIL_FROM", "MAIL_APP_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(MailNotConfigured):
        client(tmp_path, config_dir).send("日報", "x", level="公開", kind="intel_daily", day=AS_OF)


def test_sender_must_be_company(mail_env, config_dir, monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "me@gmail.com")
    with pytest.raises(MailError, match="寄件"):
        client(mail_env, config_dir).send("日報", "x", level="公開", kind="intel_daily", day=AS_OF)


def test_only_mail_client_uses_smtplib():
    hits = sorted(
        str(p.relative_to(ROOT))
        for d in ("src", "scripts")
        for p in (ROOT / d).rglob("*.py")
        if "smtplib" in p.read_text(encoding="utf-8")
    )
    assert hits == ["src/shared/mail_client.py"]


# ---- 每日推送端到端（假資料、假寄信） ----
def test_daily_push_end_to_end(mail_env, config_dir, monkeypatch):
    from intel import daily_push

    res = daily_push.run(
        daily_push.PushConfig(
            as_of=AS_OF,
            sources_path=SAMPLE / "sources_sample.yaml",
            keywords_path=SAMPLE / "keywords_sample.yaml",
            interim_dir=mail_env / "interim",
            out_dir=mail_env / "out",
            config_dir=config_dir,
            offline=True,
            log_dir=mail_env / "logs",
            mail=client(mail_env, config_dir),
            today=AS_OF,
        )
    )
    assert res.sent is True
    draft = res.draft.read_text(encoding="utf-8")
    assert draft.startswith("主旨：")
    body = draft.split("\n\n", 1)[1]
    assert body.splitlines()[0].startswith("今天有 ")  # 第一句講結論
    items = [ln for ln in body.splitlines() if ln[:3].strip().rstrip(".").isdigit()]
    assert 0 < len(items) <= 10
    assert body.count("連結：http") == len(items)
    assert "資料等級：內部一般" in body
    msg = FakeSMTP.sent[0]
    assert "永續情報日報 2026-10-14" in msg["Subject"]
    # 重要程度高的排前面
    imps = [
        int(x.split("重要程度 ")[1][0]) for x in body.splitlines() if "重要程度 " in x and "】" in x
    ]
    assert imps == sorted(imps, reverse=True)
    # 同一天重跑：不重寄，草稿相同
    res2 = daily_push.run(
        daily_push.PushConfig(
            as_of=AS_OF,
            sources_path=SAMPLE / "sources_sample.yaml",
            keywords_path=SAMPLE / "keywords_sample.yaml",
            interim_dir=mail_env / "interim",
            out_dir=mail_env / "out",
            config_dir=config_dir,
            offline=True,
            log_dir=mail_env / "logs",
            mail=client(mail_env, config_dir),
            today=AS_OF,
        )
    )
    assert res2.sent is False and len(FakeSMTP.sent) == 1


def test_no_sources_does_not_send(mail_env, config_dir, tmp_path):
    from intel import daily_push

    empty = tmp_path / "s.yaml"
    empty.write_text("sources: []\n", encoding="utf-8")
    res = daily_push.run(
        daily_push.PushConfig(
            as_of=AS_OF,
            sources_path=empty,
            keywords_path=SAMPLE / "keywords_sample.yaml",
            interim_dir=tmp_path / "interim",
            out_dir=tmp_path / "out",
            config_dir=config_dir,
            offline=True,
            log_dir=tmp_path / "logs",
            mail=client(mail_env, config_dir),
            today=AS_OF,
        )
    )
    assert res.sent is False and "來源" in res.message
    assert FakeSMTP.sent == []


def test_local_keyword_file_and_env_are_gitignored():
    r = subprocess.run(
        ["git", "check-ignore", "config/keywords.local.yaml", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.stdout.split() == ["config/keywords.local.yaml", ".env"]


def test_short_acronyms_need_word_boundary(tmp_path):
    k = kws(tmp_path, "keywords:\n  - 詞: BV\n    類別: 同業\n    權重: 3\n    同義詞: [CU, TÜV]\n")
    assert score_event(ev("It is obviously a customer"), k, {}).score == 0
    assert score_event(ev("BV 發布查證新服務"), k, {}).score == 3
    assert score_event(ev("TÜV Rheinland 年報"), k, {}).score == 3


# ---- 第一輪獨立驗收追加 ----
@pytest.mark.parametrize(
    "title, score",
    [("淨零與 ESG 新聞", 0), ("ESG 永續大會", 0), ("甲品牌 ESG 永續大會", 5 + 1)],
)
def test_restricted_alternatives_and_combos(tmp_path, title, score):
    body = """
不能單獨算的詞: [ESG, 永續, 淨零]
keywords:
  - 詞: 淨零／ESG
    類別: 議題
    權重: 2
  - 詞: ESG＋永續
    類別: 議題
    權重: 1
  - 詞: 甲品牌
    類別: 自家品牌
    權重: 5
"""
    k = kws(tmp_path, body)
    got = score_event(ev(title), k, {}).score
    assert got == (0 if score == 0 else 5 + 2 + 1)


@pytest.mark.parametrize("bad", ["A＋", "／B", "＋"])
def test_malformed_terms_warned(tmp_path, bad):
    p = tmp_path / "k.yaml"
    p.write_text(f"keywords:\n  - 詞: {bad}\n    類別: 議題\n    權重: 3\n", encoding="utf-8")
    out, problems = load_keywords(p)
    assert out == [] and any("寫法不完整" in x for x in problems)


def test_halfwidth_plus_is_literal(tmp_path):
    k = kws(tmp_path, "keywords:\n  - 詞: Scope 1+2\n    類別: 議題\n    權重: 3\n")
    assert score_event(ev("Scope 1 and 2"), k, {}).score == 0
    assert score_event(ev("Scope 1+2 排放"), k, {}).score == 3


def test_output_level_follows_keyword_file(tmp_path, config_dir):
    from intel.pipeline import RunConfig, run

    kw = tmp_path / "k.yaml"
    kw.write_text(
        (SAMPLE / "keywords_sample.yaml").read_text(encoding="utf-8") + "\n輸出等級: 內部一般\n",
        encoding="utf-8",
    )
    res = run(
        RunConfig(
            as_of=AS_OF,
            sources_path=SAMPLE / "sources_sample.yaml",
            keywords_path=kw,
            interim_dir=tmp_path / "i",
            out_dir=tmp_path / "o",
            config_dir=config_dir,
            offline=True,
            log_dir=tmp_path / "l",
        )
    )
    assert res.day["level"] == "內部一般"
    for f in res.files.values():
        if f.suffix in (".md",):
            assert "內部一般" in f.read_text(encoding="utf-8")
    s = json.loads((tmp_path / "o" / "summary.json").read_text(encoding="utf-8"))
    assert s["classification"] == "內部一般"


def test_corrupt_send_log_stops_and_partial_line_repaired(mail_env, config_dir):
    log = mail_env / "sent.jsonl"
    log.write_text('{"day": "2026-10-13", "kind": "intel_daily"}', encoding="utf-8")  # 沒有換行
    c = client(mail_env, config_dir)
    assert c.send("日報", "x", level="公開", kind="intel_daily", day=AS_OF) is True
    assert c.send("日報", "x", level="公開", kind="intel_daily", day=AS_OF) is False
    log.write_text("{壞掉\n", encoding="utf-8")
    with pytest.raises(MailError, match="第 1 行壞掉"):
        c.send("日報", "x", level="公開", kind="intel_daily", day=AS_OF)
    log.write_bytes("{}".encode("utf-16"))
    with pytest.raises(MailError, match="無法讀取"):
        c.send("日報", "x", level="公開", kind="intel_daily", day=AS_OF)


def test_only_today_can_be_sent(mail_env, config_dir):
    from intel import daily_push

    res = daily_push.run(
        daily_push.PushConfig(
            as_of=AS_OF,
            sources_path=SAMPLE / "sources_sample.yaml",
            keywords_path=SAMPLE / "keywords_sample.yaml",
            interim_dir=mail_env / "interim",
            out_dir=mail_env / "out",
            config_dir=config_dir,
            offline=True,
            log_dir=mail_env / "logs",
            mail=client(mail_env, config_dir),
            today=AS_OF - dt.timedelta(days=1),  # 指定的是「明天」的日期
        )
    )
    assert res.sent is False and "只能寄今天" in res.message and FakeSMTP.sent == []


def test_duplicate_recipients_and_percent(mail_env, config_dir, monkeypatch):
    monkeypatch.setenv("MAIL_TO", "boss@unitygood.com, BOSS@unitygood.com")
    c = client(mail_env, config_dir)
    c.send("日報", "x", level="公開", kind="intel_daily", day=AS_OF)
    assert FakeSMTP.sent[0]["To"] == "boss@unitygood.com"
    monkeypatch.setenv("MAIL_TO", "x%outside.com@unitygood.com")
    with pytest.raises(MailError, match="公司信箱"):
        client(mail_env, config_dir).send(
            "日報", "x", level="公開", kind="intel_daily", day=AS_OF + dt.timedelta(days=1)
        )


def test_unknown_level_message(mail_env, config_dir):
    with pytest.raises(MailError, match="不認得的資料等級"):
        client(mail_env, config_dir).send("日報", "x", level=" 公開", kind="intel_daily", day=AS_OF)


# ---- 第二輪獨立驗收追加 ----
def test_send_log_with_bom_ok(mail_env, config_dir):
    (mail_env / "sent.jsonl").write_text(
        '{"day": "2026-10-13", "kind": "intel_daily"}\n', encoding="utf-8-sig"
    )
    assert client(mail_env, config_dir).send(
        "日報", "x", level="公開", kind="intel_daily", day=AS_OF
    )


def test_bad_output_level_is_reported(tmp_path, config_dir):
    from intel.pipeline import RunConfig, run

    kw = tmp_path / "k.yaml"
    kw.write_text(
        (SAMPLE / "keywords_sample.yaml").read_text(encoding="utf-8") + "\n輸出等級: 亂寫\n",
        encoding="utf-8",
    )
    res = run(
        RunConfig(
            as_of=AS_OF,
            sources_path=SAMPLE / "sources_sample.yaml",
            keywords_path=kw,
            interim_dir=tmp_path / "i",
            out_dir=tmp_path / "o",
            config_dir=config_dir,
            offline=True,
            log_dir=tmp_path / "l",
        )
    )
    assert res.day["level"] == "客戶機密"
    assert any("輸出等級" in p for p in res.day["config_problems"])


def test_draft_only_does_not_overwrite_sent_draft(mail_env, config_dir):
    from intel import daily_push

    def push(send):
        return daily_push.run(
            daily_push.PushConfig(
                as_of=AS_OF,
                sources_path=SAMPLE / "sources_sample.yaml",
                keywords_path=SAMPLE / "keywords_sample.yaml",
                interim_dir=mail_env / "interim",
                out_dir=mail_env / "out",
                config_dir=config_dir,
                offline=True,
                log_dir=mail_env / "logs",
                mail=client(mail_env, config_dir),
                today=AS_OF,
                send=send,
            )
        )

    res = push(True)
    assert res.sent
    res.draft.write_text("寄出的版本", encoding="utf-8")
    push(False)
    assert res.draft.read_text(encoding="utf-8") == "寄出的版本"


# ---- 只列最近幾天發布的新聞 ----
def _rec(i, published, importance=5):
    return {
        "id": i,
        "title": f"新聞{i}",
        "url": f"https://x.example/{i}",
        "sources": ["來源"],
        "published": published,
        "score": importance,
        "importance": importance,
        "matched_terms": ["碳費"],
        "relevant": True,
    }


def _day(as_of, recs):
    return {"as_of": as_of, "run_id": "r", "records": recs, "anomalies": [], "config_problems": []}


def test_lookback_filters_old_and_undated():
    from intel.daily_push import compose

    day = _day(
        "2026-10-14",
        [
            _rec("a", "2026-10-14"),
            _rec("b", "2026-10-13"),
            _rec("c", "2026-10-12"),
            _rec("d", None),
        ],
    )
    subject, body = compose(day, 10, 1)
    assert "新聞a" in body and "新聞b" in body and "新聞c" not in body and "新聞d" not in body
    assert "另有 1 則較早發布、1 則沒有發布日期" in body
    assert body.startswith("今天有 2 則") and "（2 則）" in subject


def test_lookback_monday_includes_weekend():
    from intel.daily_push import compose, window_start

    assert window_start(dt.date(2026, 10, 19), 1) == dt.date(2026, 10, 16)  # 週一 → 上週五起
    day = _day("2026-10-19", [_rec("sat", "2026-10-17"), _rec("thu", "2026-10-15")])
    _, body = compose(day, 10, 1)
    assert "新聞sat" in body and "新聞thu" not in body


@pytest.mark.parametrize("bad", [-1, "1", True, None])
def test_bad_lookback_stops(mail_env, config_dir, bad):
    import yaml

    from intel import daily_push

    p = config_dir / "thresholds.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    d["intel"]["daily_mail_lookback_days"]["value"] = bad
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    with pytest.raises(MailError, match="daily_mail_lookback_days"):
        daily_push.run(
            daily_push.PushConfig(
                as_of=AS_OF,
                config_dir=config_dir,
                offline=True,
                interim_dir=mail_env / "i",
                out_dir=mail_env / "o",
            )
        )
