"""專案根目錄與設定檔讀取。"""

from __future__ import annotations

import re
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


def load_dotenv(path: Path | None = None) -> list[str]:
    """讀專案資料夾的 .env（KEY=VALUE），只補上尚未設定（或設成空白）的環境變數。回傳讀入的變數名稱。

    支援 # 註解（整行，或沒加引號的值後面「 #」開始的行尾註解）、前後空白、成對的單／雙引號；
    不支援變數展開。檔案不存在時不做事；不是 UTF-8 編碼時丟 ValueError（白話說明）。
    """
    import os

    path = path or PROJECT_ROOT / ".env"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(".env 不是 UTF-8 編碼，請用記事本「另存新檔」選 UTF-8 後再試") from e
    loaded = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[0] in value[1:]:
            value = value[1 : value.index(value[0], 1)]
        else:
            value = re.split(r"\s#", value, maxsplit=1)[0].strip()
        if key and not os.environ.get(key):
            os.environ[key] = value
            loaded.append(key)
    return loaded
