"""讀取並檢查各系統的 summary.json，以及週報自己的設定檔。

摘要檔的文字一律壓成一行（換行會撐破一頁版面），數值必須是有限的數字（不接受字串、布林、NaN、無限大）。
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictFloat,
    StrictInt,
    ValidationError,
)

from shared.config import PROJECT_ROOT, load_yaml

OK, STALE, MISSING, INVALID, NOT_LAUNCHED, FUTURE, FAILED = (
    "ok",
    "stale",
    "missing",
    "invalid",
    "not_launched",
    "future",
    "failed",
)
STATUS_TEXT = {
    STALE: "本週未更新",
    MISSING: "本週未更新（找不到摘要檔）",
    INVALID: "摘要檔格式錯誤，未納入",
    NOT_LAUNCHED: "系統尚未上線",
    FUTURE: "摘要檔日期晚於週報日期，未納入",
    FAILED: "本週執行失敗，未納入",
}
TEXT_MAX = 160  # 單一段文字最多幾個字，超過截斷（全文見各系統報表）


class DigestConfigError(Exception):
    """週報設定有誤（訊息為白話中文）。"""


NUMBER_MAX = 10**15  # 超過這個大小的數字視為資料錯誤


def _one_line_n(n: int):
    def f(v: Any) -> Any:
        if isinstance(v, str):
            v = " ".join(v.split())
            if len(v) > n:
                v = v[: n - 1] + "…"
        return v

    return f


_one_line = _one_line_n(TEXT_MAX)


def _finite(v):
    if v is None:
        return v
    if isinstance(v, int):
        if abs(v) > NUMBER_MAX:
            raise ValueError("數值過大")
        return v
    if not math.isfinite(v) or abs(v) > NUMBER_MAX:
        raise ValueError("數值必須是有限的數字")
    return v


Text = Annotated[str, BeforeValidator(_one_line)]
ShortText = Annotated[str, BeforeValidator(_one_line_n(12))]
Headline = Annotated[str, BeforeValidator(_one_line_n(100))]
Number = Annotated[StrictInt | StrictFloat | None, AfterValidator(_finite)]


class Metric(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    label: Text
    value: Number
    unit: ShortText = ""
    prev_value: Number = None
    source_ref: Text = ""


class AlertItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    level: str
    rule: Text
    why: Text
    subject: Text
    suggested_owner: Text = ""


class Summary(BaseModel):
    """標準摘要檔（docs/specs/digest.md）。多出來的欄位（例如 highlights）保留。"""

    model_config = ConfigDict(extra="allow")
    system: str
    run_id: Text
    as_of: dt.date
    classification: str
    headline: Headline
    metrics: list[Metric]
    alerts: list[AlertItem]
    data_quality: list[Text]


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


def _pos_int(c: dict, key: str) -> int:
    v = c.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise DigestConfigError(f"config/digest.yaml 的 {key} 應為 1 以上的整數（目前是「{v}」）")
    return v


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
        raw = c.get("systems")
        if not isinstance(raw, list) or not raw:
            raise DigestConfigError("config/digest.yaml 缺少 systems 清單")
        systems, seen = [], set()
        for i, s in enumerate(raw, start=1):
            if not isinstance(s, dict) or not s.get("key") or not s.get("name"):
                raise DigestConfigError(f"config/digest.yaml 的第 {i} 個系統缺少 key 或 name")
            if s["key"] in seen:
                raise DigestConfigError(f"config/digest.yaml 的系統「{s['key']}」重複")
            seen.add(s["key"])
            launched = s.get("launched", True)
            if not isinstance(launched, bool):
                raise DigestConfigError(
                    f"config/digest.yaml 的「{s['key']}」launched 只能寫 true 或 false（目前是「{launched}」）"
                )
            if s.get("summary"):
                path: Path | None = root / s["summary"]
            elif s.get("summary_env"):
                folder = os.environ.get(s["summary_env"], "").strip()
                path = Path(folder) / "summary.json" if folder else None
            else:
                path = None
            systems.append(SystemConfig(str(s["key"]), str(s["name"]), path, launched))
        return cls(
            tuple(systems),
            _pos_int(c, "max_chars"),
            _pos_int(c, "decisions_max"),
            _pos_int(c, "intel_max"),
            _pos_int(c, "data_quality_max"),
        )


def load_metrics(config_dir: Path | None = None) -> tuple[list[dict], str | None]:
    c = load_yaml("metrics.yaml", config_dir)
    ms = c.get("metrics")
    if not isinstance(ms, list):
        raise DigestConfigError("config/metrics.yaml 缺少 metrics 清單")
    for i, m in enumerate(ms, start=1):
        if not isinstance(m, dict) or not all(m.get(k) for k in ("key", "label", "system")):
            raise DigestConfigError(f"config/metrics.yaml 的第 {i} 個指標缺少 key、label 或 system")
    status = c.get("status")
    return ms, (status if status and status != "已確認" else None)


def read_system(
    cfg: SystemConfig, as_of: dt.date, stale_days: int | None, failed: bool = False
) -> SystemInput:
    if not cfg.launched:
        return SystemInput(cfg, NOT_LAUNCHED)
    if failed:
        return SystemInput(cfg, FAILED, reason="本週一鍵執行時這個系統沒有跑成功")
    if cfg.path is None:
        return SystemInput(cfg, MISSING, reason="設定中沒有摘要檔位置（環境變數未設定）")
    if not cfg.path.exists():
        return SystemInput(cfg, MISSING, reason=f"找不到 {cfg.path.name}")
    try:
        raw = json.loads(cfg.path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return SystemInput(cfg, INVALID, reason="摘要檔不是有效的 JSON")
    if not isinstance(raw, dict):
        return SystemInput(cfg, INVALID, reason="摘要檔內容不是一筆物件")
    try:
        summary = Summary.model_validate(raw)
    except ValidationError as e:
        fields = sorted({".".join(str(x) for x in err["loc"]) or "整份" for err in e.errors()})
        return SystemInput(cfg, INVALID, reason=f"摘要檔缺少或寫錯欄位：{'、'.join(fields[:5])}")
    if summary.system != cfg.key:
        return SystemInput(cfg, INVALID, reason=f"摘要檔標示的系統不是「{cfg.key}」")
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
