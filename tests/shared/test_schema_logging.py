import datetime as dt
import re

import pytest
from pydantic import ValidationError

from shared import logging as runlog
from shared import schema

MODELS = [
    schema.Project,
    schema.Milestone,
    schema.Contract,
    schema.Receivable,
    schema.TimeEntry,
    schema.Lead,
    schema.NewsItem,
    schema.Page,
]


@pytest.mark.parametrize("model", MODELS)
def test_every_field_has_chinese_description(model):
    for name, f in model.model_fields.items():
        assert f.description, f"{model.__name__}.{name} 缺少說明"
        assert re.search(r"[一-鿿]", f.description), f"{model.__name__}.{name} 說明不是中文"


def test_project_status_enum():
    ok = dict(
        project_id="P1",
        client="甲",
        name="案",
        owner="王",
        start_date=dt.date(2026, 1, 1),
        planned_end_date=dt.date(2026, 2, 1),
        status="進行中",
    )
    schema.Project(**ok)
    with pytest.raises(ValidationError):
        schema.Project(**{**ok, "status": "完成"})
    with pytest.raises(ValidationError):
        schema.Project(**{**ok, "未知欄位": 1})


def test_logger_writes_file(tmp_path):
    log = runlog.get_logger("t-001", tmp_path)
    log.warning("缺少欄位 負責人")
    runlog.close_logger(log)
    assert "缺少欄位 負責人" in (tmp_path / "run_t-001.log").read_text(encoding="utf-8")
