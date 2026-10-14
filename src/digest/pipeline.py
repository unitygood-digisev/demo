"""管理層週報主流程：讀各系統摘要 → 組內容 → 輸出。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from digest import output
from digest.build import Digest, build
from digest.sources import DigestConfig, SystemInput, read_system
from shared.config import PROJECT_ROOT, load_yaml, threshold


@dataclass
class RunConfig:
    as_of: dt.date
    out_dir: Path = PROJECT_ROOT / "data" / "out" / "digest"
    config_dir: Path | None = None
    root: Path = PROJECT_ROOT  # 摘要檔相對路徑的起點
    summary_overrides: dict[str, Path] = field(default_factory=dict)  # 測試或試跑用


@dataclass
class RunResult:
    digest: Digest
    inputs: list[SystemInput]
    files: dict[str, Path]


def run(cfg: RunConfig) -> RunResult:
    dcfg = DigestConfig.load(cfg.config_dir, cfg.root)
    stale_days = threshold("digest", "stale_days", cfg.config_dir)[0]
    mcfg = load_yaml("metrics.yaml", cfg.config_dir)
    inputs = []
    for s in dcfg.systems:
        if s.key in cfg.summary_overrides:
            s = type(s)(s.key, s.name, cfg.summary_overrides[s.key], s.launched)
        inputs.append(read_system(s, cfg.as_of, stale_days))
    status = mcfg.get("status")
    d = build(
        inputs,
        mcfg["metrics"],
        dcfg,
        cfg.as_of,
        status if status and status != "已確認" else None,
        stale_days,
    )
    files = output.write_all(d, cfg.out_dir)
    return RunResult(d, inputs, files)
