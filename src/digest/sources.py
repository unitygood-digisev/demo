"""讀取並檢查各系統的 summary.json。"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from shared.config import PROJECT_ROOT, load_yaml

OK, STALE, MISSING, INVALID, NOT_LAUNCHED, FUTURE = (
    "ok",
    "stale",
    "missing",
    "invalid",
    "not_launched",
    "future",
)
STATUS_TEXT = {
    STALE: "本週未更新",
    MISSING: "本週未更新（找不到摘要檔）",
    INVALID: "摘要檔格式錯誤，未納入",
    NOT_LAUNCHED: "系統尚未上線",
    FUTURE: "摘要檔日期晚於週報日期，未納入",
}


class Metric(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    label: str
    value: int | float | None
    unit: str = ""
    prev_value: int | float | None = None
    source_ref: str = ""


class AlertItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    level: str
    rule: str
    why: str
    subject: str
    suggested_owner: str = ""


class Summary(BaseModel):
    """標準摘要檔（docs/specs/digest.md）。多出來的欄位（例如 highlights）保留。"""

    model_config = ConfigDict(extra="allow")
    system: str
    run_id: str
    as_of: dt.date
    classification: str
    headline: str
    metrics: list[Metric]
    alerts: list[AlertItem]
    data_quality: list[str]


@dataclass(frozen=True)
class SystemConfig:
    key: str
    name: str
    path: Path | None
    launched: bool


@dataclass
class SystemInput:
    cfg: SystemConfig
    status: str
    summary: Summary | None = None
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == OK

    @property
    def status_text(self) -> str:
        return STATUS_TEXT.get(self.status, "")


@dataclass(frozen=True)
class DigestConfig:
    systems: tuple[SystemConfig, ...]
    max_chars: int
    decisions_max: int
    intel_max: int
    data_quality_max: int

    @classmethod
    def load(cls, config_dir: Path | None = None, root: Path = PROJECT_ROOT) -> DigestConfig:
        c = load_yaml("digest.yaml", config_dir)
        systems = []
        for s in c["systems"]:
            if s.get("summary"):
                path: Path | None = root / s["summary"]
            elif s.get("summary_env"):
                folder = os.environ.get(s["summary_env"], "").strip()
                path = Path(folder) / "summary.json" if folder else None
            else:
                path = None
            systems.append(SystemConfig(s["key"], s["name"], path, bool(s.get("launched", True))))
        return cls(
            tuple(systems),
            int(c["max_chars"]),
            int(c["decisions_max"]),
            int(c["intel_max"]),
            int(c["data_quality_max"]),
        )


def read_system(cfg: SystemConfig, as_of: dt.date, stale_days: int | None) -> SystemInput:
    if not cfg.launched:
        return SystemInput(cfg, NOT_LAUNCHED)
    if cfg.path is None:
        return SystemInput(cfg, MISSING, reason="設定中沒有摘要檔位置（環境變數未設定）")
    if not cfg.path.exists():
        return SystemInput(cfg, MISSING, reason=f"找不到 {cfg.path.name}")
    try:
        raw = json.loads(cfg.path.read_text(encoding="utf-8-sig"))
        summary = Summary.model_validate(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return SystemInput(cfg, INVALID, reason="摘要檔不是有效的 JSON")
    except ValidationError as e:
        fields = sorted({".".join(str(x) for x in err["loc"]) for err in e.errors()})
        return SystemInput(cfg, INVALID, reason=f"摘要檔缺少或寫錯欄位：{'、'.join(fields[:5])}")
    if summary.system != cfg.key:
        return SystemInput(
            cfg, INVALID, reason=f"摘要檔標示的系統是「{summary.system}」，不是「{cfg.key}」"
        )
    extra = {k: v for k, v in raw.items() if k not in Summary.model_fields}
    if summary.as_of > as_of:
        return SystemInput(
            cfg, FUTURE, summary, reason=f"摘要日期 {summary.as_of.isoformat()}", extra=extra
        )
    age = (as_of - summary.as_of).days
    if stale_days is not None and age > stale_days:
        return SystemInput(
            cfg,
            STALE,
            summary,
            reason=f"最後更新 {summary.as_of.isoformat()}，已 {age} 天",
            extra=extra,
        )
    return SystemInput(cfg, OK, summary, extra=extra)
