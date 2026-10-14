import datetime as dt
import hashlib

import pytest
from openpyxl import Workbook

from shared.io import ColumnSpec, TableSpec, issues_frame, load_table

SPEC = TableSpec(
    "projects",
    (
        ColumnSpec("project_id"),
        ColumnSpec("客戶"),
        ColumnSpec("負責人"),
        ColumnSpec("起始日", "date"),
        ColumnSpec("金額", "amount"),
        ColumnSpec("期數", "int"),
        ColumnSpec("狀態", "enum", allowed=("未開始", "進行中", "已結案", "暫停")),
        ColumnSpec("備註", required=False),
    ),
    unique_key="project_id",
)


def _xlsx(path, header, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_all_errors_listed_at_once(tmp_path):
    # 缺「負責人」「期數」兩欄；三列型別錯誤；一組重複 ID
    header = ["project_id", "客戶", "起始日", "金額", "狀態", "備註"]
    rows = [
        ["P1", "甲", dt.date(2026, 1, 1), 100, "進行中", None],  # 第 2 列
        ["P2", "乙", "2026-13-01", 200, "進行中", None],  # 第 3 列：日期錯
        ["P3", "丙", dt.date(2026, 1, 1), "一百", "進行中", None],  # 第 4 列：金額不是數字
        ["P4", "丁", dt.date(2026, 1, 1), 300, "完成了", None],  # 第 5 列：狀態不在允許值
        ["P1", "甲", dt.date(2026, 1, 1), 100, "進行中", None],  # 第 6 列：重複 ID
    ]
    p = _xlsx(tmp_path / "p.xlsx", header, rows)
    r = load_table(p, SPEC)
    got = {(i.row, i.column, i.problem.split("（")[0]) for i in r.issues}
    assert (None, "負責人", "缺少欄位") in got
    assert (None, "期數", "缺少欄位") in got
    assert (3, "起始日", "日期錯誤") in got
    assert (4, "金額", "不是數字") in got
    assert (5, "狀態", "不在允許值內") in got
    assert (2, "project_id", "重複的 ID") in got
    assert (6, "project_id", "重複的 ID") in got
    assert len(r.issues) == 7
    # 不中斷：五列都讀進來，錯誤的格子是 None
    assert len(r.data) == 5
    assert r.data.loc[r.data["_row"] == 3, "起始日"].iloc[0] is None
    assert not r.ok


def test_required_blank_and_optional_blank(tmp_path):
    header = ["project_id", "客戶", "負責人", "起始日", "金額", "期數", "狀態", "備註"]
    rows = [
        ["P1", "甲", None, "2026-01-01", "1,234", 3, "進行中", None],
        ["P2", "乙", "王", "115/01/01", 5, 2.5, "暫停", ""],
    ]
    r = load_table(_xlsx(tmp_path / "p.xlsx", header, rows), SPEC)
    probs = {(i.row, i.column, i.problem) for i in r.issues}
    assert (2, "負責人", "必填欄位空白") in probs
    assert (3, "期數", "應為整數") in probs
    assert len(r.issues) == 2  # 選填的「備註」空白不算錯
    assert r.data.loc[0, "金額"] == 1234.0
    assert r.data.loc[1, "起始日"] == dt.date(2026, 1, 1)
    assert set(r.clean["project_id"]) == set()  # 兩列都有錯


def test_column_map(tmp_path):
    header = ["編號", "客戶名稱", "負責人", "起始日", "金額", "期數", "狀態"]
    rows = [["P1", "甲", "王", "2026-01-01", 1, 1, "進行中"]]
    r = load_table(
        _xlsx(tmp_path / "p.xlsx", header, rows),
        SPEC,
        column_map={"編號": "project_id", "客戶名稱": "客戶"},
    )
    assert r.ok, r.issues
    assert r.data.loc[0, "project_id"] == "P1"


def test_csv_supported(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text(
        "project_id,客戶,負責人,起始日,金額,期數,狀態\nP1,甲,王,2026-01-01,10,1,進行中\nP2,乙,李,錯的日期,10,1,進行中\n",
        encoding="utf-8-sig",
    )
    r = load_table(p, SPEC)
    assert [(i.row, i.column) for i in r.issues] == [(3, "起始日")]


def test_raw_file_not_modified(tmp_path):
    header = ["project_id", "客戶", "起始日"]
    p = _xlsx(tmp_path / "p.xlsx", header, [["P1", None, "爛日期"]])
    before = _sha(p)
    load_table(p, SPEC, column_map={"客戶": "客戶"})
    assert _sha(p) == before


@pytest.mark.parametrize("name", ["missing.xlsx", "bad.txt"])
def test_missing_or_unsupported_file_reported_not_crash(tmp_path, name):
    p = tmp_path / name
    if name.endswith(".txt"):
        p.write_text("x", encoding="utf-8")
    r = load_table(p, SPEC)
    assert len(r.issues) == 1 and r.issues[0].row is None
    assert r.data.empty


def test_unreadable_csv_message_is_plain_chinese(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("a,b\n1,2,3,4\n", encoding="utf-8")
    r = load_table(p, SPEC)
    assert len(r.issues) == 1 and r.issues[0].problem.startswith("無法讀取檔案（常見原因")


def test_empty_file_lists_all_missing_columns(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    r = load_table(p, SPEC)
    assert not r.ok  # 空檔不能被當成「沒有錯」


def test_header_only_reported_as_no_data(tmp_path):
    header = ["project_id", "客戶", "負責人", "起始日", "金額", "期數", "狀態"]
    r = load_table(_xlsx(tmp_path / "p.xlsx", header, []), SPEC)
    assert r.data.empty
    assert [i.problem for i in r.issues] == ["檔案沒有資料列"]


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_exact_duplicate_header_reported_with_missing_columns(tmp_path, fmt):
    header = ["project_id", "客戶", "project_id", "起始日", "金額", "期數", "狀態"]
    row = ["P1", "甲", "P9", "2026-01-01", 1, 1, "進行中"]
    if fmt == "xlsx":
        p = _xlsx(tmp_path / "p.xlsx", header, [row])
    else:
        p = tmp_path / "p.csv"
        p.write_text(",".join(header) + "\n" + ",".join(map(str, row)) + "\n", encoding="utf-8")
    r = load_table(p, SPEC)
    got = {(i.column, i.problem) for i in r.issues}
    assert got == {
        ("project_id", "欄位名稱重複，無法判斷要用哪一欄"),
        ("負責人", "缺少欄位（必填）"),
    }
    assert r.data.empty


def test_duplicate_column_names_after_strip(tmp_path):
    header = ["project_id", "project_id ", "客戶", "負責人", "起始日", "金額", "期數", "狀態"]
    rows = [["P1", "P9", "甲", "王", "2026-01-01", 1, 1, "進行中"]]
    r = load_table(_xlsx(tmp_path / "p.xlsx", header, rows), SPEC)
    assert [(i.column, i.problem) for i in r.issues] == [
        ("project_id", "欄位名稱重複，無法判斷要用哪一欄")
    ]


@pytest.mark.parametrize("bad", ["inf", "-inf", "nan", "1,2,3,4", "12,34", "1.000,5", "NT$100"])
def test_bad_numbers_rejected(tmp_path, bad):
    header = ["project_id", "客戶", "負責人", "起始日", "金額", "期數", "狀態"]
    r = load_table(
        _xlsx(tmp_path / "p.xlsx", header, [["P1", "甲", "王", "2026-01-01", bad, 1, "進行中"]]),
        SPEC,
    )
    assert [(i.column, i.problem) for i in r.issues] == [("金額", "不是數字")]


@pytest.mark.parametrize(
    "good, value", [("1,234", 1234.0), ("1,234,567.5", 1234567.5), ("-500", -500.0), ("12", 12.0)]
)
def test_good_numbers_accepted(tmp_path, good, value):
    header = ["project_id", "客戶", "負責人", "起始日", "金額", "期數", "狀態"]
    r = load_table(
        _xlsx(tmp_path / "p.xlsx", header, [["P1", "甲", "王", "2026-01-01", good, 1, "進行中"]]),
        SPEC,
    )
    assert r.ok and r.data.loc[0, "金額"] == value


def test_text_na_kept_same_in_xlsx_and_csv(tmp_path):
    header = ["project_id", "客戶", "負責人", "起始日", "金額", "期數", "狀態"]
    rx = load_table(
        _xlsx(tmp_path / "p.xlsx", header, [["P1", "NA", "None", "2026-01-01", 1, 1, "進行中"]]),
        SPEC,
    )
    pc = tmp_path / "p.csv"
    pc.write_text(",".join(header) + "\nP1,NA,None,2026-01-01,1,1,進行中\n", encoding="utf-8")
    rc = load_table(pc, SPEC)
    assert rx.ok and rc.ok
    assert rx.data.loc[0, "客戶"] == rc.data.loc[0, "客戶"] == "NA"


def test_issues_frame_columns():
    df = issues_frame([])
    assert list(df.columns) == ["檔案", "列號", "欄位", "問題", "原始值"]
