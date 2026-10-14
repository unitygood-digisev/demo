"""Google 試算表連線（唯一碰到 Google 的地方），以及測試用的替身。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sheets.content import SyncError


class SheetClient(Protocol):
    def tab_titles(self) -> list[str]: ...
    def read(self, title: str) -> list[list]: ...
    def write(self, title: str, rows: list[list]) -> None: ...


def _text(v: object) -> object:
    return (
        v
        if isinstance(v, (int, float)) and not isinstance(v, bool)
        else ("" if v is None else str(v))
    )


class GspreadClient:
    """以服務帳號寫入。所有值以「原樣」寫入（RAW），以「=」開頭的文字不會變成公式。"""

    def __init__(self, credentials: Path, spreadsheet_id: str) -> None:
        import gspread
        from gspread.utils import ValueInputOption

        self._raw = ValueInputOption.raw
        try:
            gc = gspread.service_account(filename=str(credentials))
            self.sh = gc.open_by_key(spreadsheet_id)
        except FileNotFoundError as e:
            raise SyncError(
                "找不到服務帳號金鑰檔，請確認 .env 的 GOOGLE_APPLICATION_CREDENTIALS"
            ) from e
        except gspread.exceptions.SpreadsheetNotFound as e:
            raise SyncError("找不到試算表，或沒有分享給服務帳號（需要「編輯者」權限）") from e
        except gspread.exceptions.APIError as e:
            raise SyncError(
                f"Google 拒絕連線（{_status(e)}），請確認試算表已分享給服務帳號、且已啟用 Sheets API"
            ) from e
        except Exception as e:  # noqa: BLE001  金鑰格式錯、網路不通等
            raise SyncError(f"無法連上 Google 試算表（{type(e).__name__}）") from e

    def tab_titles(self) -> list[str]:
        return [ws.title for ws in self.sh.worksheets()]

    def _ws(self, title: str):
        import gspread

        try:
            return self.sh.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            return self.sh.add_worksheet(title=title, rows=100, cols=12)

    def read(self, title: str) -> list[list]:
        return self._ws(title).get_all_values()

    def write(self, title: str, rows: list[list]) -> None:
        ws = self._ws(title)
        width = max((len(r) for r in rows), default=1)
        values = [[_text(v) for v in r] + [""] * (width - len(r)) for r in rows]
        ws.clear()
        ws.update(values=values, range_name="A1", value_input_option=self._raw)


def _status(e: Exception) -> str:
    code = getattr(getattr(e, "response", None), "status_code", None)
    return f"代碼 {code}" if code else type(e).__name__


class FakeClient:
    """測試與預覽用：記在記憶體，不連網路。"""

    def __init__(self, tabs: dict[str, list[list]] | None = None) -> None:
        self.tabs: dict[str, list[list]] = {
            k: [list(r) for r in v] for k, v in (tabs or {}).items()
        }
        self.writes: list[str] = []

    def tab_titles(self) -> list[str]:
        return list(self.tabs)

    def read(self, title: str) -> list[list]:
        return [list(r) for r in self.tabs.get(title, [])]

    def write(self, title: str, rows: list[list]) -> None:
        self.writes.append(title)
        self.tabs[title] = [[_text(v) for v in r] for r in rows]
