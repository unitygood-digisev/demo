import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from sourcedraft import facts
from sourcedraft.export_docx import markdown_to_docx
from sourcedraft.ingest import load
from sourcedraft.naming import build_stem
from sourcedraft.pipeline import DraftInputs, ReplayLLM, build_step2, run
from sourcedraft.verify import verify

EX = Path(__file__).resolve().parent.parent / "examples" / "q12_training"


@pytest.fixture
def step1():
    return json.loads((EX / "reference_step1.json").read_text(encoding="utf-8"))


@pytest.fixture
def inputs():
    d = json.loads((EX / "input.json").read_text(encoding="utf-8"))
    return DraftInputs(d["past_year_final_section"], d["current_year_survey_data"], d["special_instructions"],
                       client="範例公司", year="2025", chapter="CH3")


def _calc(sheet, cid):
    return next(c for c in sheet.calcs if c.id == cid)


# ---------- v2 acceptance figures (section 三 預期輸出特徵) ----------

def test_acceptance_figures(step1):
    sheet = facts.compute(step1)
    assert _calc(sheet, "C1").display == "12,300"
    assert _calc(sheet, "C5").display == "-1.2%"
    assert _calc(sheet, "C6").display == "+8.6%"
    assert _calc(sheet, "C3").display == "32.4"
    assert _calc(sheet, "C4").display == "35.6"
    assert _calc(sheet, "C7").display == "-9.0%"
    assert sheet.flags == []


def test_v1_wrong_past_average_is_flagged(step1):
    """v1 wrote 12,450 ÷ 350 as 32.5; the self-consistency check must catch it."""
    data = copy.deepcopy(step1)
    next(f for f in data["facts"] if f["id"] == "F7")["value"] = 32.5
    sheet = facts.compute(data)
    kinds = [f.kind for f in sheet.flags]
    assert "往年不自洽" in kinds
    assert "35.6" in next(f for f in sheet.flags if f.kind == "往年不自洽").detail


def test_abnormal_swing_and_caliber_mismatch(step1):
    data = copy.deepcopy(step1)
    next(f for f in data["facts"] if f["id"] == "F4")["value"] = 500  # +42.9% headcount
    next(f for f in data["facts"] if f["id"] == "F5")["caliber"] = "年度平均人數"
    sheet = facts.compute(data)
    kinds = {f.kind for f in sheet.flags}
    assert "異常波動" in kinds
    assert "口徑不一致" in kinds


def test_safe_eval_rejects_code():
    with pytest.raises(facts.ExpressionError):
        facts.safe_eval("__import__('os').system('echo hi')")
    assert facts.safe_eval("3,200 × 2 ÷ 4") == Decimal(1600)
    assert facts.safe_eval("（1 + 2）") == Decimal(3)


def test_round_half_up():
    assert facts.quantize(Decimal("0.25"), "1dp") == Decimal("0.3")  # banker's rounding would give 0.2


# ---------- Step 3 verify ----------

def test_reference_drafts_pass(step1, inputs):
    sheet = facts.compute(step1)
    for mode in ("internal", "client"):
        draft = (EX / f"reference_draft_{mode}.md").read_text(encoding="utf-8")
        report = verify(draft, mode, inputs.sources_text(), sheet)
        assert report.errors == [], report.to_markdown()
        assert report.warnings == [], report.to_markdown()


def test_wrong_calc_marker_is_error(inputs):
    draft = ("## 3.2\n平均每人受訓 32.5 小時 [依往年完稿 3.2 計算：12,450 ÷ 350 = 32.5] [源自自收表: Q12]\n"
             "## 附錄：本章顧問審校與待補件清單\n| 序號 | 對應小節 | 狀態 | 內容 | 備忘 |\n| :- | :- | :-: | :- | :- |\n")
    report = verify(draft, "internal", inputs.sources_text())
    assert any(f.check == "計算錨點重算" for f in report.errors)


def test_fabricated_number_is_flagged(step1, inputs):
    draft = (EX / "reference_draft_internal.md").read_text(encoding="utf-8")
    draft = draft.replace("全員完課率達 92%", "全員完課率達 92%，員工滿意度達 87.5%")
    report = verify(draft, "internal", inputs.sources_text(), facts.compute(step1))
    assert any(f.check == "數值溯源" and "87.5" in f.detail for f in report.warnings)


def test_client_with_internal_markers_is_error(inputs):
    draft = "## 3.2\n總時數 12,300 小時 [源自自收表: Q12]【待顧問複核：x】\n## 客戶補件清單\n"
    report = verify(draft, "client", inputs.sources_text())
    assert len([f for f in report.errors if f.check == "模式標記"]) >= 2


def test_internal_appendix_status_values(inputs):
    draft = ("## 3.2\n總時數 12,300 小時 [源自自收表: Q12]\n## 附錄：本章顧問審校與待補件清單\n"
             "| 序號 | 對應小節 | 狀態 | 內容 | 備忘 |\n| :- | :- | :-: | :- | :- |\n| 1 | 3.2 | 處理中 | x | y |\n")
    report = verify(draft, "internal", inputs.sources_text())
    assert any(f.check == "附錄狀態" and "處理中" in f.detail for f in report.errors)
    report = verify("## 3.2\n文字 [源自自收表: Q12]\n", "internal", "")
    assert any("缺少" in f.detail for f in report.errors)


# ---------- prompt assembly / pipeline / export ----------

def test_step2_prompt_fills_all_variables(inputs, step1):
    for mode in ("internal", "client"):
        system, user = build_step2(inputs, mode, facts.compute(step1))
        assert "{{" not in system
        assert inputs.current_year_survey_data in system
        assert f"【輸出模式】：{mode}" in system
        assert "已驗算事實表" in system and "C7" in system
        assert mode in user


def test_full_run_offline(tmp_path, inputs, step1):
    llm = ReplayLLM(step1, {m: (EX / f"reference_draft_{m}.md").read_text(encoding="utf-8")
                            for m in ("internal", "client")})
    result = run(inputs, llm, tmp_path, ("internal", "client"))
    assert [d.mode for d in result.drafts] == ["internal", "client"]
    for d in result.drafts:
        assert d.files["docx"].exists() and d.files["qa"].exists()
        assert d.report.errors == []
    assert result.files["facts_json"].exists()
    # second run gets V2, never overwrites
    run(inputs, llm, tmp_path, ("internal",))
    assert (tmp_path / f"{result.drafts[0].files['markdown'].stem.replace('V1', 'V2')}.md").exists()
    assert result.drafts[0].files["markdown"].exists()  # V1 untouched


def test_naming(tmp_path):
    stem = build_stem(tmp_path, "明台產險", "2026", "CH5 永續職場", "internal", date(2026, 11, 11))
    assert stem == "明台產險_2026_初稿CH5永續職場_internal_V1_20261111"


def test_docx_roundtrip(tmp_path):
    md = (EX / "reference_draft_internal.md").read_text(encoding="utf-8")
    out = markdown_to_docx(md, tmp_path / "x.docx")
    text = load(out)
    assert "線上 ESG 數位學習平台" in text
    assert "〔表1〕" in text and "12,300" in text


def test_ingest_xlsx(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Q12"
    ws.append(["職級", "時數"])
    ws.append(["基層主管", 3200])
    wb.save(tmp_path / "s.xlsx")
    text = load(tmp_path / "s.xlsx")
    assert "〔工作表 Q12〕" in text and "| 2 | 基層主管 | 3200 |" in text


def test_list_numbering_is_not_a_figure(inputs):
    draft = ("## 3.2\n| 評核機制 | 1. 年度規劃。<br>7. 追蹤成效。 |\n| 時數 | 30.5 [源自往年完稿] |\n"
             "## 附錄：本章顧問審校與待補件清單\n| 序號 | 對應小節 | 狀態 | 內容 | 備忘 |\n| :- | :- | :-: | :- | :- |\n")
    report = verify(draft, "internal", inputs.sources_text())
    assert [f.detail for f in report.warnings if f.check == "數值溯源"] == [
        "正文數值「30.5」在輸入物料與事實表中都找不到，請確認非杜撰"]
