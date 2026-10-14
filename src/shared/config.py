"""專案根目錄與設定檔讀取。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


def load_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """讀取 config/ 下的 YAML 檔，檔案不存在時直接報錯。"""
    path = (config_dir or CONFIG_DIR) / name
    if not path.exists():
        raise FileNotFoundError(f"找不到設定檔：{path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def threshold(system: str, key: str, config_dir: Path | None = None) -> tuple[Any, str]:
    """回傳 (門檻值, 狀態)。值為 None 代表待補。"""
    data = load_yaml("thresholds.yaml", config_dir)
    try:
        item = data[system][key]
    except KeyError as e:
        raise KeyError(f"thresholds.yaml 沒有 {system}.{key}") from e
    return item.get("value"), item.get("status", "待主管確認")
