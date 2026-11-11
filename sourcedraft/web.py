"""Team web UI: login, upload materials, runs as background jobs, shared history.

Configuration (environment variables)
  ANTHROPIC_API_KEY          Claude API key (required for real runs)
  SOURCEDRAFT_USERS_FILE     accounts file, one `帳號:雜湊` per line (sourcedraft adduser)
  SOURCEDRAFT_WORK_DIR       where uploads and outputs are kept (default output/web)
  SOURCEDRAFT_MAX_JOBS       concurrent drafting jobs (default 2)
  SOURCEDRAFT_ALLOW_NO_AUTH  "1" to run without accounts (local use only)
"""

from __future__ import annotations

import html
import json
import os
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from .auth import Authenticator, load_users
from .ingest import SUPPORTED, load_many
from .pipeline import MODES, DraftInputs, ReplayLLM, run

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "q12_training"
STATUS_LABEL = {"queued": "排隊中", "running": "產出中", "done": "完成", "failed": "失敗"}


def _default_llm_factory():
    from .llm import ClaudeLLM

    return ClaudeLLM()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _mark_interrupted_jobs()
    yield


app = FastAPI(title="溯稿 SourceDraft", lifespan=_lifespan)
app.state.work_dir = Path(os.environ.get("SOURCEDRAFT_WORK_DIR", "output/web")).resolve()
app.state.llm_factory: Callable[[], Any] = _default_llm_factory
app.state.executor = ThreadPoolExecutor(max_workers=int(os.environ.get("SOURCEDRAFT_MAX_JOBS", "2")))
app.state.auth = Authenticator(load_users())
app.state.allow_no_auth = os.environ.get("SOURCEDRAFT_ALLOW_NO_AUTH") == "1"
_lock = threading.Lock()


# ---------------------------------------------------------------- auth

@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.url.path == "/healthz":
        return await call_next(request)
    auth: Authenticator = app.state.auth
    if not auth.users:
        if app.state.allow_no_auth:
            request.state.user = "local"
            return await call_next(request)
        return Response("尚未設定任何帳號：請以 sourcedraft adduser 建立帳號並設定 SOURCEDRAFT_USERS_FILE",
                        status_code=503, media_type="text/plain; charset=utf-8")
    user = auth.check(request.headers.get("authorization"))
    if user is None:
        return Response("請登入", status_code=401, media_type="text/plain; charset=utf-8",
                        headers={"WWW-Authenticate": 'Basic realm="SourceDraft", charset="UTF-8"'})
    request.state.user = user
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------- jobs on disk

def _job_dir(job: str) -> Path:
    if not job.replace("-", "").isalnum():
        raise HTTPException(404)
    return app.state.work_dir / job


def _read_job(job: str) -> dict:
    path = _job_dir(job) / "job.json"
    if not path.is_file():
        raise HTTPException(404)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_job(meta: dict) -> None:
    path = _job_dir(meta["id"]) / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)


def _list_jobs(limit: int = 30) -> list[dict]:
    root: Path = app.state.work_dir
    if not root.is_dir():
        return []
    metas = []
    for p in root.glob("*/job.json"):
        try:
            metas.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(metas, key=lambda m: m["created"], reverse=True)[:limit]


def _mark_interrupted_jobs() -> None:
    for meta in _list_jobs(limit=10_000):
        if meta["status"] in ("queued", "running"):
            meta.update(status="failed", error="伺服器重新啟動，工作中斷，請重新送出")
            _write_job(meta)


def _execute(meta: dict, inputs: DraftInputs, modes: tuple[str, ...], llm) -> None:
    meta["status"] = "running"
    _write_job(meta)
    try:
        result = run(inputs, llm, _job_dir(meta["id"]) / "out", modes)
        meta["drafts"] = [{"mode": d.mode, "errors": len(d.report.errors), "warnings": len(d.report.warnings),
                           "findings": [f.__dict__ for f in d.report.findings],
                           "files": {k: p.name for k, p in d.files.items()}} for d in result.drafts]
        if result.fact_sheet is not None:
            fs = result.fact_sheet
            meta["facts"] = {"facts": len(fs.facts), "calcs": len(fs.calcs), "gaps": len(fs.gaps),
                             "flags": [f"【{f.kind}】{f.item}：{f.detail}" for f in fs.flags]}
        meta["files"] = {k: p.name for k, p in result.files.items()}
        meta["usage"] = getattr(llm, "usage", [])
        meta["status"] = "done"
    except Exception as exc:  # surface any failure on the job page instead of losing it
        from .llm import LLMError

        meta["status"] = "failed"
        meta["error"] = str(exc) if isinstance(exc, LLMError) else f"系統錯誤：{exc!r}"
        (_job_dir(meta["id"]) / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
    meta["finished"] = datetime.now().isoformat(timespec="seconds")
    _write_job(meta)


def _submit(user: str, inputs: DraftInputs, mode: str, llm, job: str | None = None) -> str:
    job = job or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    modes = MODES if mode == "both" else (mode,)
    meta = {"id": job, "user": user, "created": datetime.now().isoformat(timespec="seconds"),
            "status": "queued", "client": inputs.client, "year": inputs.year, "chapter": inputs.chapter,
            "mode": mode}
    _write_job(meta)
    app.state.executor.submit(_execute, meta, inputs, modes, llm)
    return job


# ---------------------------------------------------------------- pages

STYLE = """
:root{--bg:#f7f7f5;--fg:#1f2328;--muted:#6b7280;--card:#fff;--line:#e5e7eb;--accent:#0f766e;--warn:#fef3c7;--err:#fee2e2}
@media (prefers-color-scheme: dark){:root{--bg:#111315;--fg:#e5e7eb;--muted:#9ca3af;--card:#1b1e21;--line:#2d3136;--accent:#2dd4bf;--warn:#3b2f0b;--err:#3b1414}}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;line-height:1.6}
main{max-width:960px;margin:0 auto;padding:24px 16px}
header{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
h1{margin:0 0 4px;font-size:1.6rem} .sub{color:var(--muted);margin:0 0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:16px;overflow-x:auto}
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


def _page(body: str, user: str = "", refresh: int | None = None) -> HTMLResponse:
    meta = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    who = f"<span class='hint'>登入：{html.escape(user)}</span>" if user else ""
    return HTMLResponse(f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
                        f"<meta name='viewport' content='width=device-width,initial-scale=1'>{meta}"
                        f"<title>溯稿 SourceDraft</title><style>{STYLE}</style></head><body><main>"
                        f"<header><h1><a href='/' style='color:inherit;text-decoration:none'>溯稿 SourceDraft</a></h1>{who}</header>"
                        f"{body}</main></body></html>")


def _jobs_table(jobs: list[dict]) -> str:
    if not jobs:
        return "<p class='hint'>尚無紀錄</p>"
    rows = "".join(
        f"<tr><td><a href='/jobs/{j['id']}'>{html.escape(j['created'].replace('T', ' '))}</a></td>"
        f"<td>{html.escape(j['client'])}</td><td>{html.escape(j['year'])}</td><td>{html.escape(j['chapter'])}</td>"
        f"<td>{html.escape(j['mode'])}</td><td>{html.escape(j['user'])}</td><td>{STATUS_LABEL[j['status']]}</td></tr>"
        for j in jobs)
    return ("<table><tr><th>送出時間</th><th>客戶</th><th>年度</th><th>章節</th><th>模式</th><th>送出者</th><th>狀態</th></tr>"
            f"{rows}</table>")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    accept = ",".join(sorted(SUPPORTED))
    return _page(f"""
<p class="sub">顧問的初稿產線：AI 負責整理和起草，人只負責審校和補件。</p>
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
<button type="submit">送出</button>
<p class="hint">送出後會轉到進度頁，一個章節約需數分鐘，可先離開，稍後從下方紀錄回來看。</p>
</form>
<div class="card"><h2>最近紀錄</h2>{_jobs_table(_list_jobs())}</div>
<form class="card" method="post" action="/demo"><strong>先看範例？</strong>
<p class="hint">用 v2 規格中的 Q12 培訓時數範例離線示範（不呼叫 API，計算與檢核為實際執行）。</p>
<button class="secondary" type="submit">跑內建範例</button></form>
<div class="card"><ol class="flow">
<li>Step 1 物料解析與事實清洗：抽出數值、缺口；所有加總／占比／平均／同比由程式驗算</li>
<li>Step 2 邏輯重構與初稿起草：依 v2 規則撰寫，只引用已驗算數值</li>
<li>Step 3 溯源錨定與風險標記：程式重算錨點、比對數值來源、檢查標記與附錄</li></ol>
<p class="hint">初稿須經顧問逐項確認事實、數據、專有名詞與揭露要求後才能交付（作業手冊 05-4）。</p></div>
""", user=request.state.user)


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


@app.post("/run")
async def run_job(request: Request, past: list[UploadFile] = File(...), survey: list[UploadFile] = File(...),
                  instructions: str = Form(""), client: str = Form(...), year: str = Form(...),
                  chapter: str = Form(...), mode: str = Form("internal")) -> RedirectResponse:
    if mode not in (*MODES, "both"):
        raise HTTPException(400, "未知的輸出模式")
    job = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    job_dir = _job_dir(job)
    past_paths = await _save_uploads(past, job_dir / "input" / "past")
    survey_paths = await _save_uploads(survey, job_dir / "input" / "survey")
    try:
        inputs = DraftInputs(load_many(past_paths), load_many(survey_paths), instructions,
                             client=client, year=year, chapter=chapter)
    except Exception as exc:
        raise HTTPException(400, f"檔案讀取失敗：{exc}") from exc
    _submit(request.state.user, inputs, mode, app.state.llm_factory(), job=job)
    return RedirectResponse(f"/jobs/{job}", status_code=303)


@app.post("/demo")
def demo(request: Request) -> RedirectResponse:
    data = json.loads((EXAMPLE_DIR / "input.json").read_text(encoding="utf-8"))
    inputs = DraftInputs(data["past_year_final_section"], data["current_year_survey_data"],
                         data["special_instructions"], client="範例公司", year="2025", chapter="3.2員工培育與發展")
    llm = ReplayLLM(json.loads((EXAMPLE_DIR / "reference_step1.json").read_text(encoding="utf-8")),
                    {m: (EXAMPLE_DIR / f"reference_draft_{m}.md").read_text(encoding="utf-8") for m in MODES})
    job = _submit(request.state.user, inputs, "both", llm)
    return RedirectResponse(f"/jobs/{job}", status_code=303)


@app.get("/jobs/{job}", response_class=HTMLResponse)
def job_page(request: Request, job: str) -> HTMLResponse:
    meta = _read_job(job)
    head = (f"<p class='sub'>{html.escape(meta['client'])} {html.escape(meta['year'])} "
            f"{html.escape(meta['chapter'])}｜{html.escape(meta['mode'])}｜送出者 {html.escape(meta['user'])}｜"
            f"{meta['created'].replace('T', ' ')}</p>")
    if meta["status"] in ("queued", "running"):
        return _page(head + f"<div class='card'><h2>{STATUS_LABEL[meta['status']]}…</h2>"
                     "<p>本頁每 10 秒自動更新。可以先離開，稍後從首頁的「最近紀錄」回來看。</p></div>",
                     user=request.state.user, refresh=10)
    if meta["status"] == "failed":
        return _page(head + f"<div class='card error'><h2>產出失敗</h2><p>{html.escape(meta.get('error', ''))}</p>"
                     "<a href='/'>返回</a></div>", user=request.state.user)

    out = f"/files/{job}"
    parts = [head]
    if meta.get("facts"):
        fs = meta["facts"]
        flags = "".join(f"<li>{html.escape(f)}</li>" for f in fs["flags"])
        links = " ｜ ".join(f"<a href='{out}/{n}'>{html.escape(n)}</a>" for n in meta.get("files", {}).values())
        parts.append(f"<div class='card'><h2>Step 1 事實表</h2><p>{fs['facts']} 筆數值、{fs['calcs']} 筆程式計算、"
                     f"{fs['gaps']} 個資料缺口、{len(fs['flags'])} 個檢核旗標</p>"
                     f"{'<ul>' + flags + '</ul>' if flags else ''}<p>{links}</p></div>")
    for d in meta.get("drafts", []):
        rows = "".join(f"<tr class='{f['level']}'><td>{f['level']}</td><td>{html.escape(f['check'])}</td>"
                       f"<td>{html.escape(f['detail'])}</td></tr>" for f in d["findings"]) or \
            "<tr><td colspan='3'>✅ 全部通過</td></tr>"
        links = " ｜ ".join(f"<a href='{out}/{n}'>{k}</a>" for k, n in d["files"].items())
        md_path = _job_dir(job) / "out" / d["files"]["markdown"]
        preview = html.escape(md_path.read_text(encoding="utf-8")) if md_path.is_file() else ""
        parts.append(f"<div class='card'><h2>{d['mode']} 版</h2><p>{links}</p>"
                     f"<h3>Step 3 自動檢核（錯誤 {d['errors']}、警示 {d['warnings']}）</h3>"
                     f"<table><tr><th>等級</th><th>項目</th><th>說明</th></tr>{rows}</table>"
                     f"<h3>預覽</h3><pre>{preview}</pre></div>")
    parts.append("<p><a href='/'>← 回首頁</a></p>")
    return _page("".join(parts), user=request.state.user)


@app.get("/files/{job}/{name}")
def files(job: str, name: str) -> FileResponse:
    base = (_job_dir(job) / "out").resolve()
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=name)
