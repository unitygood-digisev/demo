"""同步主流程：讀本機報表 → 組分頁 → 檢查 → 寫入試算表。失敗不影響本機報表。"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from shared.config import PROJECT_ROOT, load_dotenv, load_yaml
from sheets.client import GspreadClient, SheetClient
from sheets.content import (
    HISTORY_MARK,
    SYSTEM_MARK,
    SyncError,
    Tab,
    build_tabs,
    history_row,
    load_digest,
    merge_history,
)

OUT = PROJECT_ROOT / "data" / "out"
TAB_KEYS = ("digest", "alerts", "projects", "intel", "history", "info")
_BAD_TAB = re.compile(r"[\[\]/\\?*:]|\.\.")


@dataclass
class SyncConfig:
    as_of: dt.date
    config_dir: Path | None = None
    digest_dir: Path = OUT / "digest"
    progress_dir: Path = OUT / "progress"
    intel_dir: Path = OUT / "intel"
    client: SheetClient | None = None  # 測試或預覽時傳入替身
    env_file: Path | None = None  # 預設讀專案資料夾的 .env


@dataclass
class SyncResult:
    written: list[str]
    notes: list[str] = field(default_factory=list)  # 部分未更新等提醒


def settings(config_dir: Path | None = None) -> dict:
    c = load_yaml("sheets.yaml", config_dir)
    if not isinstance(c, dict):
        raise SyncError("config/sheets.yaml 格式錯誤（應為「名稱: 值」的設定）")
    if not isinstance(c.get("enabled"), bool):
        raise SyncError("config/sheets.yaml 的 enabled 只能寫 true 或 false")
    tabs = c.get("tabs")
    if not isinstance(tabs, dict):
        raise SyncError("config/sheets.yaml 缺少 tabs 設定")
    missing = [k for k in TAB_KEYS if not tabs.get(k)]
    if missing:
        raise SyncError(f"config/sheets.yaml 的 tabs 缺少：{'、'.join(missing)}")
    names = {}
    for k in TAB_KEYS:
        n = tabs[k]
        if not isinstance(n, str) or not n.strip() or len(n.strip()) > 100 or _BAD_TAB.search(n):
            raise SyncError(
                f"config/sheets.yaml 的分頁名稱「{n}」不合法（1–100 字，不可含 [ ] / \\ ? * : 或 ..）"
            )
        names[k] = n.strip()
    if len(set(names.values())) != len(TAB_KEYS):
        raise SyncError("config/sheets.yaml 的分頁名稱不能重複")
    c["tabs"] = names
    return c


def _clean_path(v: str) -> Path:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return Path(os.path.expandvars(os.path.expanduser(v)))


def connect(c: dict, env_file: Path | None = None) -> SheetClient:
    try:
        load_dotenv(env_file)
    except ValueError as e:
        raise SyncError(str(e)) from e
    sid = os.environ.get(c.get("spreadsheet_id_env", "MGMT_SHEET_ID"), "").strip().strip("\"'")
    cred = os.environ.get(c.get("credentials_env", "GOOGLE_APPLICATION_CREDENTIALS"), "").strip()
    if not sid or not cred:
        raise SyncError("尚未設定 Google 試算表（.env 缺少試算表 ID 或服務帳號金鑰路徑），略過同步")
    path = _clean_path(cred)
    if not path.is_file():
        raise SyncError("找不到服務帳號金鑰檔，請確認 .env 的 GOOGLE_APPLICATION_CREDENTIALS")
    return GspreadClient(path, sid)


def prepare(cfg: SyncConfig, c: dict) -> tuple[list[Tab], tuple[list[str], list]]:
    digest = load_digest(cfg.digest_dir, cfg.as_of)
    stem = cfg.as_of.strftime("%Y%m%d")
    progress = cfg.progress_dir / f"進度看板_{stem}.xlsx"
    intel = cfg.intel_dir / "情報追蹤表.xlsx"
    try:
        tabs = build_tabs(
            c["tabs"],
            digest,
            progress if progress.exists() else None,
            intel if intel.exists() else None,
        )
    except SyncError:
        raise
    except Exception as e:  # noqa: BLE001  其他讀檔問題也要白話
        raise SyncError(f"讀取本機報表時失敗（{type(e).__name__}），請重新產生報表") from e
    return tabs, history_row(digest)


def _check_ownership(client: SheetClient, c: dict) -> None:
    """同名分頁若不是系統寫的（例如主管自己建的），停下來，不覆蓋。"""
    existing = set(client.tab_titles())
    for k in TAB_KEYS:
        title = c["tabs"][k]
        if title not in existing:
            continue
        rows = client.read(title)
        first = str(rows[0][0]).strip() if rows and rows[0] else ""
        mark = HISTORY_MARK if k == "history" else SYSTEM_MARK
        has_content = any(str(c).strip() for r in rows for c in r)
        if has_content and not first.startswith(mark):
            raise SyncError(
                f"試算表裡已有一個「{title}」分頁，但看起來不是系統寫的，為避免覆蓋已停止同步。"
                "請把那個分頁改名，或在 config/sheets.yaml 改用其他分頁名稱"
            )


def sync(cfg: SyncConfig) -> SyncResult:
    """任何問題都丟 SyncError（白話）。寫到一半失敗時，訊息會列出哪些分頁已更新。"""
    c = settings(cfg.config_dir)
    if not c["enabled"]:
        raise SyncError("config/sheets.yaml 的 enabled 為 false，略過同步")
    tabs, (h_header, h_row) = prepare(cfg, c)
    client = cfg.client or connect(c, cfg.env_file)
    written: list[str] = []
    notes = [n for t in tabs for n in t.notes]
    hist_title = c["tabs"]["history"]
    all_titles = [t.title for t in tabs] + [hist_title]
    try:
        _check_ownership(client, c)
        for t in tabs:
            client.write(t.title, t.rows)
            written.append(t.title)
        existing = (
            client.read(hist_title, formulas=True) if hist_title in client.tab_titles() else []
        )
        merged, hist_notes = merge_history(existing, h_header, h_row)
        notes += hist_notes
        if not hist_notes:
            client.write(
                hist_title, merged, user_entered=True
            )  # 保留主管自己的公式；數字以數字寫入
        written.append(hist_title)
    except SyncError:
        raise
    except Exception as e:  # noqa: BLE001  網路中斷、配額、權限被撤銷等
        left = [t for t in all_titles if t not in written]
        part = (
            f"試算表目前部分已更新：已寫入 {'、'.join(written)}；未寫入 {'、'.join(left)}。請稍後重跑同步"
            if written
            else "試算表沒有任何改動"
        )
        raise SyncError(
            f"寫入 Google 試算表時失敗（{type(e).__name__}）。{part}。本機報表不受影響"
        ) from e
    return SyncResult(written, notes)
