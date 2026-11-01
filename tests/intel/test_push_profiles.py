"""每日情報郵件的「版本」設定（config/push_profiles.yaml）：品牌行銷部版。全部離線、不寄信。"""

import pytest
import yaml

from intel import daily_push
from intel.brief import Catalog
from intel.settings import load_keywords

from .conftest import AS_OF, ROOT, SAMPLE

CONFIG = ROOT / "config"


def test_brand_marketing_keywords_load_cleanly_and_match_topics():
    kws, problems = load_keywords(CONFIG / "keywords_brand_marketing.yaml")
    assert problems == []
    topics = {t["name"] for t in Catalog.load(None, "brief_brand_marketing.yaml").topics}
    assert {k.topic for k in kws} <= topics  # 每組關鍵字都有對應的主題
    assert "公關部" not in (CONFIG / "brief_brand_marketing.yaml").read_text(encoding="utf-8")


def test_apply_profile_separates_files_kind_and_recipients():
    cfg = daily_push.PushConfig(as_of=AS_OF)
    name = daily_push.apply_profile(cfg, "brand_marketing")
    assert name == "品牌行銷部版"
    assert cfg.keywords_path.name.startswith("keywords_brand_marketing")
    assert cfg.brief_name == "brief_brand_marketing.yaml"
    assert cfg.kind != daily_push.KIND  # 和主管版的防重寄紀錄分開
    assert cfg.recipients_env == "MAIL_TO_BRAND_MARKETING"  # 不會寄到主管版的 MAIL_TO
    assert cfg.out_dir != daily_push.PushConfig(as_of=AS_OF).out_dir
    assert cfg.per_topic == 5


def test_unknown_profile_stops():
    with pytest.raises(daily_push.ProfileError):
        daily_push.apply_profile(daily_push.PushConfig(as_of=AS_OF), "no_such_profile")


def test_profile_missing_field_stops(tmp_path):
    (tmp_path / "push_profiles.yaml").write_text(
        yaml.safe_dump({"profiles": {"x": {"名稱": "X"}}}, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(daily_push.ProfileError, match="缺少欄位"):
        daily_push.apply_profile(daily_push.PushConfig(as_of=AS_OF), "x", tmp_path)


def test_brand_marketing_draft_subject_and_name(tmp_path):
    cfg = daily_push.PushConfig(as_of=AS_OF, send=False, offline=True, today=AS_OF)
    daily_push.apply_profile(cfg, "brand_marketing")
    cfg.sources_path = SAMPLE / "sources_sample.yaml"
    cfg.interim_dir, cfg.out_dir, cfg.log_dir = tmp_path / "i", tmp_path / "o", tmp_path / "l"
    res = daily_push.run(cfg)
    assert res.sent is False
    assert res.draft.name == f"郵件_情資日報_品牌行銷部版_{AS_OF.strftime('%Y%m%d')}.txt"
    text = res.draft.read_text(encoding="utf-8")
    assert text.startswith("主旨：【優樂地】永續情資日報｜品牌行銷部版 ")
    assert "資料等級：內部一般" in text
    for banned in ("公關部", "內部敏感", "客戶機密", "副執行長"):
        assert banned not in text
    assert res.draft.with_suffix(".html").is_file()


def test_default_push_unchanged():
    cfg = daily_push.PushConfig(as_of=AS_OF)
    assert cfg.brief_name == "brief.yaml"
    assert cfg.kind == daily_push.KIND
    assert cfg.recipients_env is None
    assert cfg.draft_prefix == "郵件_情資日報"
