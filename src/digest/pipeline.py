"""管理層週報主流程：讀各系統摘要 → 組內容 → 輸出。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from digest import output
from digest.build import Digest, build
from digest.sources import DigestConfig, DigestConfigError, SystemInput, load_metrics, read_system
from shared import logging as runlog
from shared.config import PROJECT_ROOT, threshold
from shared.report import make_run_id


@dataclass
class RunConfig:
    as_of: dt.date
    out_dir: Path = PROJECT_ROOT / "data" / "out" / "digest"
    config_dir: Path | None = None
    root: Path = PROJECT_ROOT  # 摘要檔相對路徑的起點
    summary_overrides: dict[str, Path] = field(default_factory=dict)  # 測試或試跑用
    failed_systems: set[str] = field(default_factory=set)  # 本週一鍵執行時失敗的系統
    log_dir: Path | None = None


@dataclass
class RunResult:
    digest: Digest
    inputs: list[SystemInput]
    files: dict[str, Path]


def run(cfg: RunConfig) -> RunResult:
    dcfg = DigestConfig.load(cfg.config_dir, cfg.root)
    stale_days = threshold("digest", "stale_days", cfg.config_dir)[0]
    if stale_days is not None and (
        isinstance(stale_days, bool) or not isinstance(stale_days, int) or stale_days < 0
    ):
        raise DigestConfigError(
            f"config/thresholds.yaml 的 digest.stale_days 應為 0 以上的整數（目前是「{stale_days}」）"
        )
    metric_cfg, metrics_status = load_metrics(cfg.config_dir)
    inputs = []
    for s in dcfg.systems:
        if s.key in cfg.summary_overrides:
            s = type(s)(s.key, s.name, cfg.summary_overrides[s.key], s.launched)
        inputs.append(read_system(s, cfg.as_of, stale_days, failed=s.key in cfg.failed_systems))
    d = build(inputs, metric_cfg, dcfg, cfg.as_of, metrics_status, stale_days)
    used = [s.cfg.path for s in inputs if s.summary is not None and s.cfg.path is not None]
    d.run_id = make_run_id("digest", cfg.as_of, used)
    log = runlog.get_logger(d.run_id, cfg.log_dir)
    for s in inputs:
        log.info("%s：%s %s", s.cfg.key, s.status, s.reason)
    for m in d.missing:
        log.warning("待補：%s", m)
    files = output.write_all(d, cfg.out_dir)
    runlog.close_logger(log)
    return RunResult(d, inputs, files)
