"""Google 試算表連線（唯一碰到 Google 的地方），以及測試用的替身。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sheets.content import SyncError


class SheetClient(Protocol):
    def tab_titles(self) -> list[str]: ...
    def read(self, title: str, formulas: bool = False) -> list[list]: ...
    def write(self, title: str, rows: list[list]) -> None: ...

    def update_cells(self, title: str, cells: list[tuple[int, int, object]]) -> None: ...


def _text(v: object) -> object:
    return (
        v
        if isinstance(v, (int, float)) and not isinstance(v, bool)
        else ("" if v is None else str(v))
    )


def _pad(rows: list[list], old_rows: int, old_cols: int) -> list[list]:
    """把新內容補成至少與舊內容一樣大，一次寫入就能蓋掉舊內容（不先清空，寫入失敗時舊內容還在）。"""
    width = max([len(r) for r in rows] + [old_cols, 1])
    height = max(len(rows), old_rows)
    out = [[_text(v) for v in r] + [""] * (width - len(r)) for r in rows]
    out += [[""] * width for _ in range(height - len(rows))]
    return out


class GspreadClient:
    """以服務帳號寫入。系統分頁一律以「原樣」寫入（以「=」開頭的文字不會變成公式）。"""

    def __init__(self, credentials: Path, spreadsheet_id: str) -> None:
        import gspread
        from gspread.utils import DateTimeOption, ValueInputOption, ValueRenderOption

        self._gspread = gspread
        self._raw = ValueInputOption.raw
        self._formula = ValueRenderOption.formula
        self._date_text = DateTimeOption.formatted_string
        try:
            gc = gspread.service_account(filename=str(credentials))
            self.sh = gc.open_by_key(spreadsheet_id)
        except FileNotFoundError as e:
            raise SyncError(
                "找不到服務帳號金鑰檔，請確認 .env 的 GOOGLE_APPLICATION_CREDENTIALS"
            ) from e
        except (ValueError, KeyError) as e:
            raise SyncError("服務帳號金鑰檔格式不對，請重新從 Google Cloud 下載 JSON 金鑰") from e
        except gspread.exceptions.SpreadsheetNotFound as e:
            raise SyncError("找不到試算表，或沒有分享給服務帳號（需要「編輯者」權限）") from e
        except gspread.exceptions.APIError as e:
            raise SyncError(
                f"Google 拒絕連線（{_status(e)}），請確認試算表已分享給服務帳號、且已啟用 Sheets API"
            ) from e
        except Exception as e:  # noqa: BLE001  金鑰內容錯誤、網路不通等
            raise SyncError(
                f"無法連上 Google 試算表（{type(e).__name__}），請確認網路與金鑰檔"
            ) from e

    def tab_titles(self) -> list[str]:
        return [ws.title for ws in self.sh.worksheets()]

    def _ws(self, title: str):
        try:
            return self.sh.worksheet(title)
        except self._gspread.exceptions.WorksheetNotFound:
            return self.sh.add_worksheet(title=title, rows=100, cols=12)

    def read(self, title: str, formulas: bool = False) -> list[list]:
        ws = self._ws(title)
        return (
            ws.get_all_values(
                value_render_option=self._formula,
                date_time_render_option=self._date_text,
            )
            if formulas
            else ws.get_all_values()
        )

    def write(self, title: str, rows: list[list]) -> None:
        ws = self._ws(title)
        old = ws.get_all_values()
        values = _pad(rows, len(old), max((len(r) for r in old), default=0))
        if len(values) > ws.row_count or (values and len(values[0]) > ws.col_count):
            ws.resize(rows=max(len(values), ws.row_count), cols=max(len(values[0]), ws.col_count))
        ws.update(values=values, range_name="A1", value_input_option=self._raw)

    def update_cells(self, title: str, cells: list[tuple[int, int, object]]) -> None:
        """只改指定的格子（原樣寫入），其他格子不動。"""
        from gspread.utils import rowcol_to_a1

        if not cells:
            return
        ws = self._ws(title)
        need_r = max(r for r, _, _ in cells) + 1
        need_c = max(c for _, c, _ in cells) + 1
        if need_r > ws.row_count or need_c > ws.col_count:
            ws.resize(rows=max(need_r, ws.row_count), cols=max(need_c, ws.col_count))
        ws.batch_update(
            [{"range": rowcol_to_a1(r + 1, c + 1), "values": [[_text(v)]]} for r, c, v in cells],
            value_input_option=self._raw,
        )


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

    def read(self, title: str, formulas: bool = False) -> list[list]:
        return [list(r) for r in self.tabs.get(title, [])]

    def write(self, title: str, rows: list[list]) -> None:
        self.writes.append(title)
        self.tabs[title] = [[_text(v) for v in r] for r in rows]

    def update_cells(self, title: str, cells: list[tuple[int, int, object]]) -> None:
        self.writes.append(title)
        rows = self.tabs.setdefault(title, [])
        for r, c, v in cells:
            while len(rows) <= r:
                rows.append([])
            rows[r] += [""] * max(0, c + 1 - len(rows[r]))
            rows[r][c] = _text(v)
