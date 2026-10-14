import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from shared.llm_client import LLMClient, LLMNotConfiguredError, LLMPolicyError

ROOT = Path(__file__).resolve().parents[2]
SECRET_INPUT = "這是一段不應該出現在日誌裡的文章全文 ABC-123"


@pytest.fixture
def client(tmp_path):
    calls = []

    def responder(prompt, text):
        calls.append(text)
        return "模擬摘要"

    c = LLMClient(
        cache_dir=tmp_path / "cache", log_path=tmp_path / "calls.jsonl", mock_responder=responder
    )
    c.calls = calls
    return c


def _call(c, level, purpose="intel_summary", backend=None):
    return c.complete(
        level=level,
        purpose=purpose,
        prompt_version="v0-test",
        prompt="請摘要",
        input_text=SECRET_INPUT,
        backend=backend,
    )


def _log(c):
    return [json.loads(x) for x in c.log_path.read_text(encoding="utf-8").splitlines()]


def test_public_intel_summary_allowed(client):
    r = _call(client, "公開")
    assert r.text == "模擬摘要" and not r.cached and r.backend == "mock"
    rec = _log(client)[-1]
    assert rec["status"] == "ok" and rec["level"] == "公開" and rec["prompt_version"] == "v0-test"


@pytest.mark.parametrize("level", ["內部一般", "內部敏感", "客戶機密"])
def test_intel_summary_rejects_higher_levels(client, level):
    with pytest.raises(LLMPolicyError, match="最高只能處理「公開」"):
        _call(client, level)
    assert client.calls == []  # 模型完全沒被呼叫
    assert _log(client)[-1]["status"] == "rejected"


@pytest.mark.parametrize("level", [None, "", "機密", "public"])
def test_missing_or_unknown_level_rejected(client, level):
    with pytest.raises(LLMPolicyError):
        _call(client, level, purpose="test")
    assert client.calls == []


def test_unregistered_purpose_rejected(client):
    with pytest.raises(LLMPolicyError, match="未在 llm.yaml 登記"):
        _call(client, "公開", purpose="隨便用用")


@pytest.mark.parametrize(
    "level, backend",
    [
        ("內部一般", "cloud_public"),
        ("內部敏感", "cloud_public"),
        ("內部敏感", "cloud_company"),
        ("客戶機密", "cloud_public"),
        ("客戶機密", "cloud_company"),
    ],
)
def test_backend_not_allowed_for_level(client, level, backend):
    with pytest.raises(LLMPolicyError, match="不允許使用後端"):
        _call(client, level, purpose="test", backend=backend)
    assert _log(client)[-1]["status"] == "rejected"


def test_unknown_backend_rejected(client):
    with pytest.raises(LLMPolicyError):
        _call(client, "公開", backend="不存在")


def test_allowed_but_unconfigured_backend_fails_loudly(client):
    # 內部一般 + 公司帳號是規則允許的，但階段 0 尚未實作真實後端
    with pytest.raises(LLMNotConfiguredError):
        _call(client, "內部一般", purpose="test", backend="cloud_company")


def test_log_has_hash_not_full_text(client):
    _call(client, "公開")
    with pytest.raises(LLMPolicyError):
        _call(client, "客戶機密")
    raw = client.log_path.read_text(encoding="utf-8")
    assert SECRET_INPUT not in raw and "ABC-123" not in raw
    for rec in _log(client):
        assert re.fullmatch(r"[0-9a-f]{64}", rec["input_hash"])
        assert {"time", "level", "prompt_version", "input_hash", "status"} <= rec.keys()


def test_cache_same_input(client):
    a = _call(client, "公開")
    b = _call(client, "公開")
    assert not a.cached and b.cached and a.text == b.text
    assert len(client.calls) == 1


def test_cache_differs_by_prompt_version(client):
    _call(client, "公開")
    client.complete(
        level="公開",
        purpose="intel_summary",
        prompt_version="v1",
        prompt="請摘要",
        input_text=SECRET_INPUT,
    )
    assert len(client.calls) == 2


def test_temperature_must_be_zero(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    data = yaml.safe_load((cfg / "llm.yaml").read_text(encoding="utf-8"))
    data["temperature"] = 0.7
    (cfg / "llm.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="temperature"):
        LLMClient(config_dir=cfg)


SDK_PATTERN = re.compile(
    r"^\s*(import|from)\s+(anthropic|openai|google\.generativeai|google\.genai|cohere|mistralai|ollama|langchain\w*|litellm|transformers)\b",
    re.M,
)


def test_no_direct_llm_sdk_imports():
    hits = []
    for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
        if SDK_PATTERN.search(p.read_text(encoding="utf-8")):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == [], f"這些檔案直接 import 大模型 SDK：{hits}"
