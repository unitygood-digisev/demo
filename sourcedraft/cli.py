"""溯稿 SourceDraft command line.

  sourcedraft draft   --past 往年.docx --survey 自收表.docx [...]   產出初稿
  sourcedraft prompt  --past ... --survey ...                         只輸出組好的提示詞（貼到 Dify / Claude Project）
  sourcedraft verify  初稿.md --sources 往年.docx 自收表.docx         對既有初稿跑 Step 3 檢核
  sourcedraft demo                                                     離線跑內建範例（不呼叫 API）
  sourcedraft serve                                                    啟動網頁介面
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import facts as facts_mod
from .ingest import load_many
from .pipeline import MODES, DraftInputs, ReplayLLM, build_step1, build_step2, run
from .verify import verify

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "q12_training"


def _modes(value: str) -> tuple[str, ...]:
    return MODES if value == "both" else (value,)


def _inputs(args: argparse.Namespace) -> DraftInputs:
    instructions = args.instructions or ""
    if args.instructions_file:
        instructions = Path(args.instructions_file).read_text(encoding="utf-8")
    return DraftInputs(
        past_year_final_section=load_many([Path(p) for p in args.past]),
        current_year_survey_data=load_many([Path(p) for p in args.survey]),
        special_instructions=instructions,
        client=args.client, year=args.year, chapter=args.chapter,
    )


def _add_input_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--past", nargs="+", required=True, help="往年完稿章節（docx/pdf/md/txt，可多檔）")
    p.add_argument("--survey", nargs="+", required=True, help="當年自收表（docx/xlsx/pdf/md/txt，可多檔）")
    p.add_argument("--instructions", default="", help="補充要求／特殊披露重點")
    p.add_argument("--instructions-file", help="補充要求檔案")
    p.add_argument("--client", default="客戶", help="客戶簡稱，用於檔名")
    p.add_argument("--year", default="", help="報導年度，用於檔名")
    p.add_argument("--chapter", default="章節", help="章節代號，例如 CH5永續職場")
    p.add_argument("--mode", choices=["internal", "client", "both"], default="internal")


def _print_run(result) -> int:
    worst = 0
    if result.fact_sheet is not None:
        fs = result.fact_sheet
        print(f"Step 1：{len(fs.facts)} 筆數值、{len(fs.calcs)} 筆計算、{len(fs.gaps)} 個缺口、{len(fs.flags)} 個檢核旗標")
    for d in result.drafts:
        r = d.report
        print(f"[{d.mode}] Step 3 檢核：錯誤 {len(r.errors)}、警示 {len(r.warnings)}")
        for f in r.errors:
            print(f"   ❌ {f.check}：{f.detail}")
        for key, path in d.files.items():
            print(f"   {key:8s} → {path}")
        worst = max(worst, 1 if r.errors else 0)
    for key, path in result.files.items():
        print(f"{key:12s} → {path}")
    return worst


def cmd_draft(args: argparse.Namespace) -> int:
    from .llm import ClaudeLLM, LLMError

    llm = ClaudeLLM(model=args.model, effort=args.effort)
    try:
        result = run(_inputs(args), llm, Path(args.out), _modes(args.mode), use_fact_sheet=not args.no_fact_sheet)
    except LLMError as exc:
        print(f"失敗：{exc}", file=sys.stderr)
        return 2
    code = _print_run(result)
    for u in llm.usage:
        print(f"usage: {u}")
    return code


def cmd_prompt(args: argparse.Namespace) -> int:
    inputs = _inputs(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    s1_sys, s1_user = build_step1(inputs)
    (out / "step1_system.md").write_text(s1_sys, encoding="utf-8")
    (out / "step1_user.md").write_text(s1_user, encoding="utf-8")
    for mode in _modes(args.mode):
        system, user = build_step2(inputs, mode, None)
        (out / f"step2_system_{mode}.md").write_text(system, encoding="utf-8")
    print(f"提示詞已輸出至 {out}（step2 為單次呼叫版，未含程式驗算事實表）")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    draft = Path(args.draft).read_text(encoding="utf-8")
    sources = load_many([Path(p) for p in args.sources]) if args.sources else ""
    sheet = None
    if args.facts:
        sheet = facts_mod.compute(json.loads(Path(args.facts).read_text(encoding="utf-8")))
    report = verify(draft, args.mode, sources, sheet)
    print(report.to_markdown())
    return 1 if report.errors else 0


def cmd_demo(args: argparse.Namespace) -> int:
    ex = EXAMPLE_DIR
    data = json.loads((ex / "input.json").read_text(encoding="utf-8"))
    inputs = DraftInputs(data["past_year_final_section"], data["current_year_survey_data"],
                         data["special_instructions"], client="範例公司", year="2025", chapter="3.2員工培育與發展")
    llm = ReplayLLM(json.loads((ex / "reference_step1.json").read_text(encoding="utf-8")),
                    {"internal": (ex / "reference_draft_internal.md").read_text(encoding="utf-8"),
                     "client": (ex / "reference_draft_client.md").read_text(encoding="utf-8")})
    print("（離線示範：Step 1／Step 2 使用內建參考輸出（人工撰寫的驗收樣本），計算與檢核為實際執行）")
    return _print_run(run(inputs, llm, Path(args.out), MODES))


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("sourcedraft.web:app", host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sourcedraft", description="溯稿 SourceDraft：永續報告書初稿產線")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("draft", help="產出章節初稿")
    _add_input_args(p)
    p.add_argument("--out", default="output")
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--no-fact-sheet", action="store_true", help="略過 Step 1 程式驗算，只用 v2 提示詞單次起草")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("prompt", help="輸出組好的提示詞，不呼叫 API")
    _add_input_args(p)
    p.add_argument("--out", default="output/prompts")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("verify", help="對既有初稿跑 Step 3 檢核")
    p.add_argument("draft")
    p.add_argument("--mode", choices=list(MODES), default="internal")
    p.add_argument("--sources", nargs="*", help="輸入物料（用於數值溯源比對）")
    p.add_argument("--facts", help="Step 1 事實表 JSON")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("demo", help="離線跑內建範例")
    p.add_argument("--out", default="output/demo")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("serve", help="啟動網頁介面")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    if getattr(args, "model", "x") is None:
        from .llm import DEFAULT_MODEL
        args.model = DEFAULT_MODEL
    if getattr(args, "effort", "x") is None:
        from .llm import DEFAULT_EFFORT
        args.effort = DEFAULT_EFFORT
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
