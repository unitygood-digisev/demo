"""項目進度看板主流程：讀看板 → 規則 → 與上次比較 → 存紀錄 → 輸出。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from progress import output
from progress.board import BoardConfig, ProgressDataError, find_input, load_board
from progress.history import History, compare
from progress.rules import evaluate
from shared import logging as runlog
from shared.config import PROJECT_ROOT, threshold
from shared.report import make_run_id

LEVEL = "內部一般"
TH_KEYS = ("P02_due_soon_days", "P04_unchanged_days", "P05_max_active_projects", "board_stale_days")


@dataclass
class RunConfig:
    as_of: dt.date
    input_path: Path | None = None  # 未指定時，取 data/raw/ 下最新的看板
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    interim_dir: Path = PROJECT_ROOT / "data" / "interim" / "progress"
    out_dir: Path = PROJECT_ROOT / "data" / "out" / "progress"
    config_dir: Path | None = None
    log_dir: Path | None = None


@dataclass
class RunResult:
    run_id: str
    data: dict
    files: dict[str, Path] = field(default_factory=dict)


def run(cfg: RunConfig) -> RunResult:
    bcfg = BoardConfig.load(cfg.config_dir)
    th = {k: threshold("progress", k, cfg.config_dir)[0] for k in TH_KEYS}
    hist = History(cfg.interim_dir)
    latest = hist.latest_run_date()
    if latest and cfg.as_of < latest:
        raise ProgressDataError(
            f"指定的日期 {cfg.as_of.isoformat()} 早於已處理過的最新日期 {latest.isoformat()}。"
            "往前補跑會打亂歷次紀錄，已停止執行，沒有改動任何檔案。"
        )
    path = cfg.input_path or find_input(cfg.raw_dir, bcfg)
    if not path.exists():
        raise ProgressDataError(f"找不到看板檔案 {path.name}")
    board = load_board(path, bcfg)
    run_id = make_run_id("progress", cfg.as_of, [path])
    log = runlog.get_logger(run_id, cfg.log_dir)

    since, earliest = hist.unchanged_since(board, cfg.as_of)
    stale_n = th["P04_unchanged_days"]
    history_ok = (
        earliest is not None and stale_n is not None and (cfg.as_of - earliest).days >= stale_n
    )
    ev = evaluate(board, cfg.as_of, bcfg, th, since, history_ok)
    # 日期本身寫錯的列，已在資料品質列出「日期錯誤」，不再重複列「沒有下一個日期」
    bad_dates = {i.row for i in board.issues if i.column == "下一個日期"}
    ev.quality = [q for q in ev.quality if not (q.field == "下一個日期" and q.row in bad_dates)]

    notes = list(ev.notes)
    board_note = None
    if board.board_date is None:
        notes.append("看板上沒有標示資料日期（標題列上方的說明文字中找不到日期）")
    elif (
        th["board_stale_days"] is not None
        and (cfg.as_of - board.board_date).days > th["board_stale_days"]
    ):
        board_note = (
            f"看板資料日期是 {board.board_date.isoformat()}，距今 {(cfg.as_of - board.board_date).days} 天，"
            "內容可能沒有更新，部分「已過日期」的案子可能其實已完成"
        )

    alerts = [a.__dict__ for a in ev.alerts]
    projects = sorted({r["案子"] for r in board.rows})
    prev = hist.previous_run(cfg.as_of)
    changes = compare(prev[1] if prev else None, alerts, projects)
    if prev:
        changes["prev_date"] = prev[0].isoformat()

    active = [r for r in board.rows if r.get("階段") in bcfg.active_stages]
    lights = ev.lights
    metrics = {
        "red_projects": sum(1 for v in lights.values() if v == "紅"),
        "yellow_projects": sum(1 for v in lights.values() if v == "黃"),
        "green_projects": sum(1 for v in lights.values() if v == "綠"),
        "active_projects": len(active),
        "missing_next_date": sum(1 for q in ev.quality if q.field == "下一個日期"),
        "total_projects": len(board.rows),
    }
    data = {
        "as_of": cfg.as_of.isoformat(),
        "run_id": run_id,
        "level": LEVEL,
        "input_file": path.name,
        "board_date": board.board_date.isoformat() if board.board_date else None,
        "board_note": board_note,
        "thresholds": th,
        "alerts": alerts,
        "projects": projects,
        "metrics": metrics,
        "prev_metrics": prev[1]["metrics"] if prev else None,
        "changes": changes,
        "notes": notes,
    }
    for a in ev.alerts:
        log.info("預警 %s %s：%s", a.rule, a.level, a.why)
    for i in board.issues:
        log.warning("資料品質：第 %s 列 %s %s", i.row, i.column, i.problem)

    files = output.write_all(data, board, ev, bcfg, cfg.out_dir, cfg.as_of)
    hist.save(
        cfg.as_of, board, {k: data[k] for k in ("as_of", "run_id", "alerts", "projects", "metrics")}
    )
    runlog.close_logger(log)
    return RunResult(run_id, data, files)
