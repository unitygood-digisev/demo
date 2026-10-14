import datetime as dt
import shutil
import socket
from pathlib import Path

import pytest
import yaml

from intel.pipeline import RunConfig
from intel.summarize import intel_mock_responder
from shared.llm_client import LLMClient

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample" / "feeds"
AS_OF = dt.date(2026, 10, 14)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """系統 7 的測試一律不准連網路。"""

    def boom(*a, **k):
        raise AssertionError("測試中不允許連網路")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    import requests

    monkeypatch.setattr(requests, "get", boom)


@pytest.fixture
def config_dir(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    return cfg


def set_threshold(config_dir: Path, key: str, value) -> None:
    p = config_dir / "thresholds.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["intel"][key]["value"] = value
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


class SpyClient(LLMClient):
    """記錄每次呼叫的資料等級。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.levels: list = []

    def complete(self, **kw):
        self.levels.append(kw.get("level"))
        return super().complete(**kw)


@pytest.fixture
def make_cfg(tmp_path, config_dir):
    def _make(as_of=AS_OF, responder=intel_mock_responder, **kw) -> RunConfig:
        llm = SpyClient(
            config_dir=config_dir,
            cache_dir=tmp_path / "llm_cache",
            log_path=tmp_path / "logs" / "model_calls.jsonl",
            mock_responder=responder,
        )
        base = dict(
            as_of=as_of,
            sources_path=SAMPLE / "sources_sample.yaml",
            keywords_path=SAMPLE / "keywords_sample.yaml",
            interim_dir=tmp_path / "interim",
            out_dir=tmp_path / "out",
            config_dir=config_dir,
            offline=True,
            weekly=True,
            llm=llm,
            log_dir=tmp_path / "logs",
        )
        base.update(kw)
        return RunConfig(**base)

    return _make
