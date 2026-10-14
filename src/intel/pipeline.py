"""外部情報主流程：抓取 → 整理 → 去重 → 評分 → 摘要 → 存檔 → 輸出。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from intel import output
from intel.dedupe import Event, dedupe
from intel.fetch import Fetcher, HttpGet
from intel.normalize import to_items
from intel.score import score_event
from intel.settings import load_keywords, load_sources
from intel.store import DayStore, IntelDataError, SeenStore
from intel.summarize import Summarizer, intel_mock_responder
from shared import logging as runlog
from shared.config import PROJECT_ROOT, threshold
from shared.dates import TW_TZ
from shared.llm_client import LLMClient
from shared.report import make_run_id


@dataclass
class RunConfig:
    as_of: dt.date
    sources_path: Path = PROJECT_ROOT / "config" / "sources.yaml"
    keywords_path: Path = PROJECT_ROOT / "config" / "keywords.yaml"
    interim_dir: Path = PROJECT_ROOT / "data" / "interim" / "intel"
    out_dir: Path = PROJECT_ROOT / "data" / "out" / "intel"
    prompt_path: Path = PROJECT_ROOT / "prompts" / "intel_summary.md"
    config_dir: Path | None = None  # 讀 thresholds／llm／classification 的資料夾
    offline: bool = False
    weekly: bool = False
    http_get: HttpGet | None = None
    llm: LLMClient | None = None
    sleep: object = None
    log_dir: Path | None = None
    root: Path = PROJECT_ROOT  # 本機來源檔只能放在這個資料夾內


@dataclass
class RunResult:
    run_id: str
    day: dict
    files: dict[str, Path] = field(default_factory=dict)


def _thresholds(cfg: RunConfig) -> dict:
    out = {}
    for key in ("relevance_min_score", "title_similarity_dup", "max_items_per_issue"):
        out[key] = threshold("intel", key, cfg.config_dir)[0]
    return out


def run(cfg: RunConfig) -> RunResult:
    th = _thresholds(cfg)
    seen = SeenStore(cfg.interim_dir / "seen.csv")
    if seen.latest and cfg.as_of < seen.latest:
        raise IntelDataError(
            f"指定的日期 {cfg.as_of.isoformat()} 早於已處理過的最新日期 {seen.latest.isoformat()}。"
            "往前回補會打亂「第一次看到」的紀錄，已停止執行，沒有改動任何檔案。"
        )
    sources, src_problems = load_sources(cfg.sources_path)
    keywords, kw_problems = load_keywords(cfg.keywords_path)
    config_problems = src_problems + kw_problems
    if not sources:
        config_problems.append("來源清單是空的，請依 config/sources.yaml 的說明填寫")
    if not keywords:
        config_problems.append(
            "關鍵字清單是空的，所有文章都會是 0 分，請依 config/keywords.yaml 的說明填寫"
        )
    src_map = {s.id: s for s in sources}
    rank = {s.id: i for i, s in enumerate(sources)}

    # 1. 抓取
    fetch_kwargs = {"sleep": cfg.sleep} if cfg.sleep else {}
    fetcher = Fetcher(
        cfg.root, cfg.interim_dir / "raw", cfg.as_of, cfg.offline, cfg.http_get, **fetch_kwargs
    )
    fetched_at = dt.datetime.now(TW_TZ)
    anomalies: list[dict] = []
    items = []
    raw_files: list[Path] = []
    for s in sources:
        r = fetcher.fetch(s)
        if r.raw_path:
            raw_files.append(r.raw_path)
        if r.error:
            anomalies.append({"source": s.name, "reason": r.error, "level": "error"})
            continue
        if r.warning:
            anomalies.append({"source": s.name, "reason": r.warning, "level": "warning"})
        its, probs = to_items(r, fetched_at)
        items.extend(its)
        anomalies.extend({"source": s.name, "reason": p, "level": "warning"} for p in probs)

    run_id = make_run_id("intel", cfg.as_of, [cfg.sources_path, cfg.keywords_path, *raw_files])
    log = runlog.get_logger(run_id, cfg.log_dir)
    for a in anomalies:
        log.warning("來源異常：%s：%s", a["source"], a["reason"])
    for p in config_problems:
        log.warning("設定問題：%s", p)

    # 2. 去重、跨次執行判斷
    events = dedupe(items, rank, th["title_similarity_dup"])
    new_events: list[Event] = []
    related: dict[str, dict] = {}  # 舊事件的後續報導 → 先前報導
    for ev in events:
        if seen.first_seen_of(ev.member_ids, cfg.as_of) == cfg.as_of:
            new_events.append(ev)
            continue
        # 已看過的事件：今天才出現的新報導另列一則，避免新連結消失
        fresh = [m for m in ev.members if seen.is_new(m.id, cfg.as_of)]
        if fresh:
            old = min(
                (m for m in ev.members if not seen.is_new(m.id, cfg.as_of)),
                key=lambda m: (seen.first_seen[m.id], m.id),
            )
            sub_ev = Event(fresh[0], fresh[1:])
            new_events.append(sub_ev)
            related[sub_ev.id] = {
                "title": old.title,
                "first_seen": seen.first_seen[old.id].isoformat(),
            }
    for ev in events:
        seen.mark(ev.member_ids, cfg.as_of)

    # 3. 評分、相關判斷、每期上限
    scored = [(ev, score_event(ev, keywords, src_map)) for ev in new_events]
    min_score = th["relevance_min_score"]
    relevant = [x for x in scored if min_score is None or x[1].score >= min_score]
    relevant.sort(
        key=lambda x: (
            -x[1].score,
            -(x[0].main.published.timestamp() if x[0].main.published else 0),
            x[0].id,
        )
    )
    over_cap: set[str] = set()
    cap = th["max_items_per_issue"]
    if cap is not None and len(relevant) > cap:
        over_cap = {ev.id for ev, _ in relevant[cap:]}
        relevant = relevant[:cap]
    relevant_ids = {ev.id for ev, _ in relevant}

    # 4. 摘要（只對相關者）
    llm = cfg.llm or LLMClient(config_dir=cfg.config_dir, mock_responder=intel_mock_responder)
    summarizer = Summarizer(llm, cfg.prompt_path)
    records = []
    for ev, sc in scored:
        rel = ev.id in relevant_ids
        summary = summarizer.summarize(ev, run_id).as_dict() if rel else None
        records.append(
            {
                "id": ev.id,
                "member_ids": ev.member_ids,
                "title": ev.main.title,
                "url": ev.main.url,
                "extra_urls": ev.extra_urls,
                "sources": [src_map[s].name for s in ev.source_ids if s in src_map],
                "published": ev.main.published.date().isoformat() if ev.main.published else None,
                "first_seen": cfg.as_of.isoformat(),
                "score": sc.score,
                "matched_terms": list(sc.matched_terms),
                "group": sc.group,
                "relevant": rel,
                "excluded_reason": "超過每期上限"
                if ev.id in over_cap
                else (None if rel else "相關度低於門檻"),
                "summary": summary,
                "related_to": related.get(ev.id),
            }
        )
    records.sort(key=lambda r: (not r["relevant"], -r["score"], r["published"] or "", r["id"]))

    day = {
        "as_of": cfg.as_of.isoformat(),
        "run_id": run_id,
        "records": records,
        "anomalies": anomalies,
        "config_problems": config_problems,
        "thresholds": th,
        "mock": summarizer.mock,
        "prompt_version": summarizer.version,
        "input_files": [cfg.sources_path.name, cfg.keywords_path.name]
        + sorted({p.name for p in raw_files}),
    }
    days = DayStore(cfg.interim_dir / "days")
    days.save(cfg.as_of, day)
    seen.save()

    files = output.write_all(day, days, cfg.out_dir, cfg.as_of, cfg.weekly)
    runlog.close_logger(log)
    return RunResult(run_id, day, files)
