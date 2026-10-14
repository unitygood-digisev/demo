"""同步主流程：讀本機報表 → 組分頁 → 寫入試算表。失敗不影響本機報表。"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

from shared.config import PROJECT_ROOT, load_yaml
from sheets.client import GspreadClient, SheetClient
from sheets.content import (
    SyncError,
    Tab,
    build_tabs,
    history_row,
    latest,
    load_digest,
    merge_history,
)

OUT = PROJECT_ROOT / "data" / "out"


@dataclass
class SyncConfig:
    as_of: dt.date
    config_dir: Path | None = None
    digest_dir: Path = OUT / "digest"
    progress_dir: Path = OUT / "progress"
    intel_dir: Path = OUT / "intel"
    client: SheetClient | None = None  # 測試或預覽時傳入替身


def settings(config_dir: Path | None = None) -> dict:
    c = load_yaml("sheets.yaml", config_dir)
    tabs = c.get("tabs") or {}
    need = ("digest", "alerts", "projects", "intel", "history", "info")
    missing = [k for k in need if not tabs.get(k)]
    if missing:
        raise SyncError(f"config/sheets.yaml 的 tabs 缺少：{'、'.join(missing)}")
    if len({tabs[k] for k in need}) != len(need):
        raise SyncError("config/sheets.yaml 的分頁名稱不能重複")
    if not isinstance(c.get("enabled"), bool):
        raise SyncError("config/sheets.yaml 的 enabled 只能寫 true 或 false")
    return c


def connect(c: dict) -> SheetClient:
    sid = os.environ.get(c.get("spreadsheet_id_env", "MGMT_SHEET_ID"), "").strip()
    cred = os.environ.get(c.get("credentials_env", "GOOGLE_APPLICATION_CREDENTIALS"), "").strip()
    if not sid or not cred:
        raise SyncError("尚未設定 Google 試算表（.env 缺少試算表 ID 或服務帳號金鑰路徑），略過同步")
    if not Path(cred).is_file():
        raise SyncError("找不到服務帳號金鑰檔，請確認 .env 的 GOOGLE_APPLICATION_CREDENTIALS")
    return GspreadClient(Path(cred), sid)


def prepare(cfg: SyncConfig, c: dict) -> tuple[list[Tab], tuple[list[str], list]]:
    digest = load_digest(cfg.digest_dir, cfg.as_of)
    stem = cfg.as_of.strftime("%Y%m%d")
    progress = cfg.progress_dir / f"進度看板_{stem}.xlsx"
    intel = cfg.intel_dir / "情報追蹤表.xlsx"
    tabs = build_tabs(
        c["tabs"],
        digest,
        progress if progress.exists() else None,
        intel if intel.exists() else latest(cfg.intel_dir, "情報追蹤表*.xlsx"),
    )
    return tabs, history_row(digest)


def sync(cfg: SyncConfig) -> list[str]:
    """回傳已寫入的分頁名稱。任何問題都丟 SyncError（白話）。"""
    c = settings(cfg.config_dir)
    if not c["enabled"]:
        raise SyncError("config/sheets.yaml 的 enabled 為 false，略過同步")
    tabs, (h_header, h_row) = prepare(cfg, c)
    client = cfg.client or connect(c)
    try:
        for t in tabs:
            client.write(t.title, t.rows)
        hist_title = c["tabs"]["history"]
        existing = client.read(hist_title) if hist_title in client.tab_titles() else []
        client.write(hist_title, merge_history(existing, h_header, h_row))
    except SyncError:
        raise
    except Exception as e:  # noqa: BLE001  網路中斷、配額、權限被撤銷等
        raise SyncError(f"寫入 Google 試算表時失敗（{type(e).__name__}），本機報表不受影響") from e
    return [t.title for t in tabs] + [hist_title]
