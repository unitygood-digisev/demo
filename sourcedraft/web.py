"""Minimal internal web UI: upload materials, get draft + QA report + fact sheet.

Run with `sourcedraft serve` (binds to 127.0.0.1 by default; this is an internal tool,
put it behind your own auth before exposing it to a network).
"""

from __future__ import annotations

import html
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .ingest import SUPPORTED, load_many
from .pipeline import MODES, DraftInputs, ReplayLLM, run

WORK_DIR = Path(os.environ.get("SOURCEDRAFT_WORK_DIR", "output/web")).resolve()
EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "q12_training"

app = FastAPI(title="溯稿 SourceDraft")

STYLE = """
:root{--bg:#f7f7f5;--fg:#1f2328;--muted:#6b7280;--card:#fff;--line:#e5e7eb;--accent:#0f766e;--warn:#fef3c7;--err:#fee2e2}
@media (prefers-color-scheme: dark){:root{--bg:#111315;--fg:#e5e7eb;--muted:#9ca3af;--card:#1b1e21;--line:#2d3136;--accent:#2dd4bf;--warn:#3b2f0b;--err:#3b1414}}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{margin:0 0 4px;font-size:1.6rem} .sub{color:var(--muted);margin:0 0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:16px}
label{display:block;font-weight:600;margin:12px 0 4px} .hint{font-weight:400;color:var(--muted);font-size:.85rem}
input[type=text],textarea,select{width:100%;box-sizing:border-box;padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer;margin-top:16px}
button.secondary{background:transparent;color:var(--accent);border:1px solid var(--accent)}
table{border-collapse:collapse;width:100%;font-size:.9rem} td,th{border:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
.error{background:var(--err)} .warning{background:var(--warn)}
pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:12px;max-height:480px;overflow:auto;font-size:.85rem}
a{color:var(--accent)} ol.flow{padding-left:20px;color:var(--muted)}
"""


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
                        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
                        f"<title>溯稿 SourceDraft</title><style>{STYLE}</style></head><body><main>{body}</main></body></html>")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    accept = ",".join(sorted(SUPPORTED))
    return _page(f"""
<h1>溯稿 SourceDraft</h1>
<p class="sub">顧問的初稿產線：AI 負責整理和起草，人只負責審校和補件。</p>
<div class="card"><ol class="flow">
<li>Step 1 物料解析與事實清洗：抽出數值、缺口；所有加總／占比／平均／同比由程式驗算</li>
<li>Step 2 邏輯重構與初稿起草：依 v2 規則撰寫，只引用已驗算數值</li>
<li>Step 3 溯源錨定與風險標記：程式重算錨點、比對數值來源、檢查標記與附錄</li></ol></div>
<form class="card" method="post" action="/run" enctype="multipart/form-data">
<label>往年完稿章節 <span class="hint">（{accept}，可多檔）</span></label>
<input type="file" name="past" multiple required accept="{accept}">
<label>當年自收表 <span class="hint">（可多檔，含附件）</span></label>
<input type="file" name="survey" multiple required accept="{accept}">
<label>補充要求／特殊披露重點 <span class="hint">（可空白）</span></label>
<textarea name="instructions" rows="3"></textarea>
<div class="row">
<div><label>客戶簡稱</label><input type="text" name="client" placeholder="明台產險" required></div>
<div><label>報導年度</label><input type="text" name="year" placeholder="2026" required></div>
<div><label>章節代號</label><input type="text" name="chapter" placeholder="CH5永續職場" required></div>
<div><label>輸出模式</label><select name="mode">
<option value="internal">internal（顧問版）</option><option value="client">client（客戶版）</option>
<option value="both">兩版都要</option></select></div></div>
<button type="submit">產出初稿</button>
<p class="hint">一個章節約需數分鐘，請勿關閉頁面。</p>
</form>
<form class="card" method="post" action="/demo"><strong>先看範例？</strong>
<p class="hint">用 v2 規格中的 Q12 培訓時數範例離線示範（不呼叫 API，計算與檢核為實際執行）。</p>
<button class="secondary" type="submit">跑內建範例</button></form>
""")


async def _save_uploads(files: list[UploadFile], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        name = Path(f.filename or "upload").name
        if Path(name).suffix.lower() not in SUPPORTED:
            raise HTTPException(400, f"不支援的檔案格式：{name}")
        p = dest / name
        p.write_bytes(await f.read())
        paths.append(p)
    return paths


def _result_page(job: str, result) -> HTMLResponse:
    parts = [f"<h1>初稿完成</h1><p class='sub'>工作編號 {job}</p>"]
    if result.fact_sheet is not None:
        fs = result.fact_sheet
        flags = "".join(f"<li>【{html.escape(f.kind)}】{html.escape(f.item)}：{html.escape(f.detail)}</li>" for f in fs.flags)
        parts.append(f"<div class='card'><h2>Step 1 事實表</h2><p>{len(fs.facts)} 筆數值、{len(fs.calcs)} 筆程式計算、"
                     f"{len(fs.gaps)} 個資料缺口、{len(fs.flags)} 個檢核旗標</p>"
                     f"{'<ul>' + flags + '</ul>' if flags else ''}"
                     + "".join(f"<a href='/files/{job}/{p.name}'>下載 {p.name}</a><br>" for p in result.files.values())
                     + "</div>")
    for d in result.drafts:
        rows = "".join(f"<tr class='{f.level}'><td>{f.level}</td><td>{html.escape(f.check)}</td>"
                       f"<td>{html.escape(f.detail)}</td></tr>" for f in d.report.findings) or \
            "<tr><td colspan='3'>✅ 全部通過</td></tr>"
        links = " ｜ ".join(f"<a href='/files/{job}/{p.name}'>{k}</a>" for k, p in d.files.items())
        parts.append(f"<div class='card'><h2>{d.mode} 版</h2><p>{links}</p>"
                     f"<h3>Step 3 自動檢核（錯誤 {len(d.report.errors)}、警示 {len(d.report.warnings)}）</h3>"
                     f"<table><tr><th>等級</th><th>項目</th><th>說明</th></tr>{rows}</table>"
                     f"<h3>預覽</h3><pre>{html.escape(d.markdown)}</pre></div>")
    parts.append("<p><a href='/'>← 再跑一個章節</a></p>")
    return _page("".join(parts))


@app.post("/run", response_class=HTMLResponse)
async def run_job(past: list[UploadFile] = File(...), survey: list[UploadFile] = File(...),
                  instructions: str = Form(""), client: str = Form(...), year: str = Form(...),
                  chapter: str = Form(...), mode: str = Form("internal")) -> HTMLResponse:
    from .llm import ClaudeLLM, LLMError

    job = uuid.uuid4().hex[:12]
    job_dir = WORK_DIR / job
    past_paths = await _save_uploads(past, job_dir / "input" / "past")
    survey_paths = await _save_uploads(survey, job_dir / "input" / "survey")
    inputs = DraftInputs(load_many(past_paths), load_many(survey_paths), instructions,
                         client=client, year=year, chapter=chapter)
    modes = MODES if mode == "both" else (mode,)
    try:
        result = run(inputs, ClaudeLLM(), job_dir, modes)
    except LLMError as exc:
        return _page(f"<div class='card error'><h2>產出失敗</h2><p>{html.escape(str(exc))}</p>"
                     f"<a href='/'>返回</a></div>")
    return _result_page(job, result)


@app.post("/demo", response_class=HTMLResponse)
def demo() -> HTMLResponse:
    data = json.loads((EXAMPLE_DIR / "input.json").read_text(encoding="utf-8"))
    inputs = DraftInputs(data["past_year_final_section"], data["current_year_survey_data"],
                         data["special_instructions"], client="範例公司", year="2025", chapter="3.2員工培育與發展")
    llm = ReplayLLM(json.loads((EXAMPLE_DIR / "reference_step1.json").read_text(encoding="utf-8")),
                    {m: (EXAMPLE_DIR / f"reference_draft_{m}.md").read_text(encoding="utf-8") for m in MODES})
    job = "demo-" + uuid.uuid4().hex[:8]
    return _result_page(job, run(inputs, llm, WORK_DIR / job, MODES))


@app.get("/files/{job}/{name}")
def files(job: str, name: str) -> FileResponse:
    path = (WORK_DIR / job / name).resolve()
    if path.parent != (WORK_DIR / job).resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=name)
