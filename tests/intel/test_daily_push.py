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
