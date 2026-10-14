import datetime as dt
import shutil
from pathlib import Path

import pytest
import yaml

from progress.pipeline import RunConfig, run

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample" / "progress"
WEEKS = (dt.date(2026, 9, 30), dt.date(2026, 10, 7), dt.date(2026, 10, 14))
AS_OF = WEEKS[-1]


def sample_board(day: dt.date) -> Path:
    return SAMPLE / f"項目進度看板_假資料_{day.strftime('%Y%m%d')}.xlsx"


@pytest.fixture
def config_dir(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    return cfg


def set_threshold(config_dir: Path, key: str, value) -> None:
    p = config_dir / "thresholds.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["progress"][key]["value"] = value
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def make_cfg(tmp_path, config_dir):
    def _make(as_of=AS_OF, input_path="sample", **kw) -> RunConfig:
        base = dict(
            as_of=as_of,
            input_path=sample_board(as_of) if input_path == "sample" else input_path,
            raw_dir=tmp_path / "raw",
            interim_dir=tmp_path / "interim",
            out_dir=tmp_path / "out",
            config_dir=config_dir,
            log_dir=tmp_path / "logs",
        )
        base.update(kw)
        return RunConfig(**base)

    return _make


@pytest.fixture
def three_weeks(make_cfg):
    """依序跑 9/30、10/7、10/14 三週，回傳最後一次的結果。"""

    def _run():
        res = None
        for d in WEEKS:
            res = run(make_cfg(as_of=d))
        return res

    return _run
