"""SourceDraft pipeline: Step 1 extract + compute → Step 2 draft → Step 3 verify → export."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from . import facts as facts_mod
from .export_docx import markdown_to_docx
from .llm import LLM
from .naming import build_stem
from .verify import QAReport, verify

MODES = ("internal", "client")


def _prompt(name: str) -> str:
    return resources.files("sourcedraft").joinpath("prompts", name).read_text(encoding="utf-8")


@dataclass
class DraftInputs:
    past_year_final_section: str
    current_year_survey_data: str
    special_instructions: str = ""
    client: str = "客戶"
    year: str = ""
    chapter: str = "章節"

    def sources_text(self) -> str:
        return "\n".join([self.past_year_final_section, self.current_year_survey_data, self.special_instructions])


@dataclass
class DraftResult:
    mode: str
    markdown: str
    report: QAReport
    files: dict[str, Path] = field(default_factory=dict)


@dataclass
class RunResult:
    fact_sheet: facts_mod.FactSheet | None
    drafts: list[DraftResult]
    files: dict[str, Path] = field(default_factory=dict)


def render_inputs_block(inputs: DraftInputs) -> str:
    return (f"<past_year_final_section>\n{inputs.past_year_final_section}\n</past_year_final_section>\n\n"
            f"<current_year_survey_data>\n{inputs.current_year_survey_data}\n</current_year_survey_data>\n\n"
            f"<special_instructions>\n{inputs.special_instructions or '（無）'}\n</special_instructions>")


def build_step1(inputs: DraftInputs) -> tuple[str, str]:
    return _prompt("step1_extract.md"), render_inputs_block(inputs) + "\n\n請輸出事實表 JSON。"


def build_step2(inputs: DraftInputs, mode: str, sheet: facts_mod.FactSheet | None) -> tuple[str, str]:
    """The v2 system prompt with its {{variables}} filled, plus the verified fact sheet."""
    system = _prompt("system_prompt_v2.md")
    values = {
        "past_year_final_section": "\n" + inputs.past_year_final_section,
        "current_year_survey_data": "\n" + inputs.current_year_survey_data,
        "special_instructions": inputs.special_instructions or "（無）",
        "output_mode": mode,
    }
    for key, val in values.items():
        system = system.replace("{{" + key + "}}", val)
    if sheet is not None:
        system += "\n\n" + _prompt("step2_fact_sheet_addendum.md").replace(
            "{{fact_sheet}}", facts_mod.render_fact_sheet(sheet))
    return system, f"OUTPUT_MODE = {mode}。請依上述規則開始執行，直接輸出章節初稿。"


def run_step1(inputs: DraftInputs, llm: LLM) -> facts_mod.FactSheet:
    system, user = build_step1(inputs)
    data = llm.extract(system, user, facts_mod.STEP1_SCHEMA)
    return facts_mod.compute(data)


def run(inputs: DraftInputs, llm: LLM, out_dir: Path, modes: tuple[str, ...] = ("internal",),
        use_fact_sheet: bool = True, export: bool = True) -> RunResult:
    for m in modes:
        if m not in MODES:
            raise ValueError(f"未知的輸出模式：{m}")
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = run_step1(inputs, llm) if use_fact_sheet else None
    result = RunResult(fact_sheet=sheet, drafts=[])

    for mode in modes:
        system, user = build_step2(inputs, mode, sheet)
        markdown = llm.draft(system, user).strip() + "\n"
        report = verify(markdown, mode, inputs.sources_text(), sheet)
        draft = DraftResult(mode=mode, markdown=markdown, report=report)
        if export:
            stem = build_stem(out_dir, inputs.client, inputs.year, inputs.chapter, mode)
            md_path = out_dir / f"{stem}.md"
            md_path.write_text(markdown, encoding="utf-8")
            draft.files["markdown"] = md_path
            draft.files["docx"] = markdown_to_docx(markdown, out_dir / f"{stem}.docx",
                                                   title=f"{inputs.client} {inputs.chapter} 初稿")
            qa_path = out_dir / f"{stem}_自動檢核報告.md"
            qa_path.write_text(report.to_markdown(), encoding="utf-8")
            draft.files["qa"] = qa_path
            if sheet is not None and "facts" not in result.files:
                fs_path = out_dir / f"{stem}_事實表.md"
                fs_path.write_text("# 溯稿 Step 1 已驗算事實表\n\n" + facts_mod.render_fact_sheet(sheet),
                                   encoding="utf-8")
                json_path = out_dir / f"{stem}_事實表.json"
                json_path.write_text(json.dumps(sheet.data, ensure_ascii=False, indent=2), encoding="utf-8")
                result.files["facts"] = fs_path
                result.files["facts_json"] = json_path
        result.drafts.append(draft)
    return result


class ReplayLLM:
    """Offline LLM that returns recorded outputs; used by tests and the bundled demo."""

    def __init__(self, step1: dict[str, Any] | None, drafts: dict[str, str]):
        self.step1 = step1
        self.drafts = drafts
        self.calls: list[tuple[str, str]] = []

    def extract(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("extract", system))
        if self.step1 is None:
            raise RuntimeError("ReplayLLM 沒有 Step 1 錄製輸出")
        return self.step1

    def draft(self, system: str, user: str) -> str:
        self.calls.append(("draft", system))
        mode = "client" if "OUTPUT_MODE = client" in user else "internal"
        return self.drafts[mode]
