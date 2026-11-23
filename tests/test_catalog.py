from pathlib import Path

from sourcedraft import catalog as C

F = C.FOLDER


def item(i, title, parent, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", mod="2026-01-01T00:00:00Z"):
    return {"id": i, "title": title, "parentId": parent, "mimeType": mime, "modifiedTime": mod,
            "owner": "x@unitygood.com", "viewUrl": f"https://drive/{i}", "fileSize": "1"}


LISTING = [
    item("f_final", "07 最終版", "R1", F),
    item("a", "FINAL_2025年永續報告書第4章-附錄.docx", "f_final"),
    item("b", "2025年永續報告書第4章-附錄_V6.docx", "f_draft"),
    item("f_draft", "04 草稿", "R1", F),
    item("f_survey", "03 資蒐表", "R1", F),
    item("f_ch5", "CH5 永續職場", "f_survey", F),
    item("c", "明台資蒐表_CH5永續職場.docx", "f_ch5"),
    item("d", "文稿二版各部門資料蒐集表0604.xlsx", "f_survey",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    item("f_cert", "05 外部確信", "R1", F),
    item("e", "意見與建議_0723送審版.xlsx", "R2", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    item("g", "BSI_OFI鉤稽表_台北慈濟醫院2025永續報告書.xlsx", "f_cert"),
    item("h", "1150115-台北慈濟ESG全文V4.pdf", "R2", "application/pdf"),
    item("i", "2025台北慈濟醫院永續報告書final.pdf", "R2", "application/pdf"),
    item("j", "~$合版】台北慈濟2025年永續報告書_資料蒐集表v1.docx", "R2"),
    item("k", "東華醫院_永續報告書啟始會議20260714.pptx", "R2",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    item("f_git", ".git", "R2", F),
    item("l", "config", "f_git", "application/octet-stream"),
    item("m", "outside.docx", "NOT_INDEXED"),
]
ROOTS = {"R1": "明台產險", "R2": "台北慈濟醫院"}


def by_title(entries):
    return {e.title: e for e in entries}


def test_build_classifies_real_titles():
    es = by_title(C.build(LISTING, ROOTS))
    assert es["FINAL_2025年永續報告書第4章-附錄.docx"].role == "往年完稿"
    assert es["FINAL_2025年永續報告書第4章-附錄.docx"].year == "2025"
    assert es["FINAL_2025年永續報告書第4章-附錄.docx"].path == "07 最終版"
    assert es["2025年永續報告書第4章-附錄_V6.docx"].stage == "05 撰稿"
    assert es["2025年永續報告書第4章-附錄_V6.docx"].role == "其他"
    assert es["明台資蒐表_CH5永續職場.docx"].role == "自收表"
    assert es["明台資蒐表_CH5永續職場.docx"].path == "03 資蒐表／CH5 永續職場"
    assert es["文稿二版各部門資料蒐集表0604.xlsx"].role == "自收表"
    assert es["意見與建議_0723送審版.xlsx"].role == "查證意見"
    assert es["BSI_OFI鉤稽表_台北慈濟醫院2025永續報告書.xlsx"].role == "查證意見"  # not 往年完稿
    assert es["2025台北慈濟醫院永續報告書final.pdf"].role == "往年完稿"
    assert es["1150115-台北慈濟ESG全文V4.pdf"].year == "2026"  # 民國 115 date prefix
    assert es["東華醫院_永續報告書啟始會議20260714.pptx"].stage == "01 啟動"
    assert "config" not in es and "outside.docx" not in es  # .git and out-of-tree skipped
    assert not any(t.startswith("~$") for t in es)  # Office lock files skipped


def test_detect_year():
    assert C.detect_year("114年醫院評鑑") == "2025"
    assert C.detect_year("常春組織圖11401.pdf") == ""  # 5-digit 民國年月 is ambiguous, leave blank
    assert C.detect_year("2026報告書") == "2026"
    assert C.detect_year("台北慈濟醫院") == ""
    assert C.detect_year("114~118年短中長期目標") == "2025"


def test_full_report_files_and_publication_dates():
    listing = [
        item("p", "2025報告書", "R1", F),
        item("x1", "1150828-彬台ESG全文-V4.pdf", "p", "application/pdf"),
        item("x2", "2025嘉義基督教醫院永續報告書.docx", "R2"),
        item("x3", "2025嘉義基督教醫院永續報告書S2後_整合完成版_修.docx", "R2"),
    ]
    es = by_title(C.build(listing, ROOTS))
    assert es["1150828-彬台ESG全文-V4.pdf"].year == "2025"  # folder year beats the 民國 publication date
    assert es["1150828-彬台ESG全文-V4.pdf"].role == "往年完稿"
    assert es["2025嘉義基督教醫院永續報告書.docx"].role == "往年完稿"
    assert es["2025嘉義基督教醫院永續報告書S2後_整合完成版_修.docx"].role != "往年完稿"


def test_suggest_and_csv_roundtrip(tmp_path):
    es = C.build(LISTING, ROOTS)
    s = C.suggest(es, "明台產險", "2026")
    assert [e.title for e in s["往年完稿"]] == ["FINAL_2025年永續報告書第4章-附錄.docx"]
    assert {e.title for e in s["自收表"]} == {"明台資蒐表_CH5永續職場.docx", "文稿二版各部門資料蒐集表0604.xlsx"}
    p = tmp_path / "c.csv"
    C.write_csv(es, p)
    assert C.read_csv(p) == es
    summary = {r["client"]: r for r in C.summarize(es)}
    assert summary["明台產險"]["往年完稿"] == 1 and summary["明台產險"]["自收表"] == 2


def test_meeting_decks_and_peer_reports_are_not_finals():
    listing = [
        item("q", "顧問建議資料", "R1", F),
        item("y1", "常春醫院＿永續報告書結案會議1028.pdf", "q", "application/pdf"),
        item("y2", "永續報告書目標指標範例.docx", "q"),
        item("r", "參考資料", "R1", F), item("r2", "其他醫院永續報告書", "r", F),
        item("y3", "2024_中國醫CSR_線上版_-20250805改-最終版.pdf", "r2", "application/pdf"),
        item("y4", "●擎邦2025永續報告書-S2查證終版V1.docx", "R1"),
    ]
    es = by_title(C.build(listing, ROOTS))
    assert es["常春醫院＿永續報告書結案會議1028.pdf"].role != "往年完稿"
    assert es["永續報告書目標指標範例.docx"].role != "往年完稿"
    assert es["2024_中國醫CSR_線上版_-20250805改-最終版.pdf"].role == "同業參考"
    assert es["●擎邦2025永續報告書-S2查證終版V1.docx"].role == "往年完稿"
