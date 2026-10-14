"""統一日誌：每次執行一份 logs/run_<執行編號>.log，同時輸出到畫面。

以 `from shared import logging as runlog` 引用，避免與 Python 內建 logging 混淆。
"""

from __future__ import annotations

import logging as _std_logging
from pathlib import Path

from shared.config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def get_logger(run_id: str, log_dir: Path | None = None) -> _std_logging.Logger:
    """取得某次執行的 logger。同一個 run_id 重複呼叫會拿到同一個，不會重複寫入。"""
    log_dir = log_dir or LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = _std_logging.getLogger(f"unity.{run_id}")
    if not logger.handlers:
        logger.setLevel(_std_logging.INFO)
        fh = _std_logging.FileHandler(log_dir / f"run_{run_id}.log", encoding="utf-8")
        fh.setFormatter(_std_logging.Formatter(_FORMAT))
        logger.addHandler(fh)
        sh = _std_logging.StreamHandler()
        sh.setFormatter(_std_logging.Formatter(_FORMAT))
        sh.setLevel(_std_logging.WARNING)
        logger.addHandler(sh)
        logger.propagate = False
    return logger


def close_logger(logger: _std_logging.Logger) -> None:
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
