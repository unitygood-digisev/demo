"""會議紀錄 → 看板補齊建議（階段 2b）。

看板通常比會議紀錄新，所以**不改看板**，只產生建議：
  1. 看板沒填下一個日期、紀錄裡有看板日期之後的日期 → 建議補上的日期
  2. 看板的日期或階段和紀錄不一樣 → 只提醒（以看板為準）
  3. 紀錄提到、看板上找不到的名稱 → 請人確認是否漏列
  4. 對到多個案子、看板同名、對不到案子的日期 → 待人工確認
輸出只有案名、日期、階段字眼與出處（檔名＋行號），不輸出紀錄原文。
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from progress.board import BoardConfig, ProgressDataError, find_input, load_board
from progress.meetings import Line, Meeting, MeetingRules, match_cases, norm, parse_meeting
from shared import logging as runlog
from shared.config import PROJECT_ROOT, threshold
from shared.report import Footer, make_run_id, write_xlsx

LEVEL = "內部一般"
SHEETS = ("建議補上的日期", "與看板不一致", "看板沒有的案子", "待人工確認", "會議紀錄清單")


@dataclass
class BackfillConfig:
    as_of: dt.date
    board_path: Path | None = None  # 未指定時，取 data/raw/ 下最新的看板
    meetings_dir: Path | None = None  # 未指定時，取 data/raw/<meetings.yaml 的 folder>
    aliases_path: Path | None = None  # 未指定時，取 meetings.yaml 的 aliases_file
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    out_dir: Path = PROJECT_ROOT / "data" / "out" / "progress"
    config_dir: Path | None = None
    log_dir: Path | None = None


@dataclass
class BackfillResult:
    run_id: str
    path: Path
    headline: str
    notes: list[str] = field(default_factory=list)


@dataclass
class Mention:
    file: str
    line: int
    meeting: dt.date
    exact: list[dt.date]
    approx: list
    words: list[str]

    @property
    def where(self) -> str:
        return f"{self.file} 第 {self.line} 行"


def _max_age(config_dir: Path | None) -> int:
    try:
        v = threshold("meetings", "max_age_days", config_dir)[0]
    except KeyError as e:
        raise ProgressDataError("config/thresholds.yaml 缺少 meetings.max_age_days，請補上") from e
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ProgressDataError(
            f"config/thresholds.yaml 的 meetings.max_age_days 應為 0 以上的整數（目前是「{v}」），請修正後再跑"
        )
    return v


def _aliases(
    path: Path, cases: list[str]
) -> tuple[dict[str, str], set[str], list[str], list[dict]]:
    """回傳 (對應表, 不是案子的名稱, 提醒, 待人工確認列)。對應到看板上沒有的案名，列入待人工確認、不使用。"""
    if not path.is_file():
        return (
            {},
            set(),
            [
                f"沒有案名對應表（{path.name}），簡稱可能對不到看板；可參考 meeting_aliases.example.yaml 建立"
            ],
            [],
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = data.get("aliases") or {}
        ignore = data.get("ignore") or []
        if not isinstance(raw, dict) or not isinstance(ignore, list):
            raise ValueError
    except (yaml.YAMLError, UnicodeDecodeError, ValueError, AttributeError) as e:
        raise ProgressDataError(f"案名對應表 {path.name} 格式錯誤，請參考範例檔修正") from e
    good, manual = {}, []
    for k, v in raw.items():
        if v is None or not str(v).strip():
            manual.append(
                {
                    "出處": path.name,
                    "日期": "",
                    "原因": f"對應表的「{k}」沒有寫看板案名，未使用",
                    "可能的案子": "",
                }
            )
        elif str(v) in cases:
            good[str(k)] = str(v)
        else:
            manual.append(
                {
                    "出處": path.name,
                    "日期": "",
                    "原因": f"對應表的「{k}」對到看板上沒有的案名，未使用",
                    "可能的案子": str(v),
                }
            )
    return good, {norm(str(x)) for x in ignore}, [], manual


def _fmt(ds) -> str:
    return "、".join(d.isoformat() for d in sorted(set(ds))) or ""


def _approx_text(items) -> str:
    seen = []
    for a in items:
        if a.label not in seen:
            seen.append(a.label)
    return "、".join(seen)


def _file_status(m: Meeting, board_date: dt.date, max_age: int, as_of: dt.date) -> tuple[bool, str]:
    if m.problem:
        return False, m.problem
    notes = []
    if m.date > as_of:
        notes.append("檔名日期晚於執行日，請確認日期是否寫錯")
    if m.text_date and m.text_date != m.date:
        notes.append(f"內文的會議日期（{m.text_date.isoformat()}）和檔名不符，以檔名為準")
    age = (board_date - m.date).days
    if age > max_age:
        return False, "；".join([f"比看板早 {age} 天（超過 {max_age} 天），只存檔、不比對", *notes])
    status = "比看板新，已比對" if age < 0 else f"比看板早 {age} 天，已比對"
    return True, "；".join([status, *notes])


def run(cfg: BackfillConfig) -> BackfillResult:
    rules = MeetingRules.load(cfg.config_dir)
    max_age = _max_age(cfg.config_dir)
    bcfg = BoardConfig.load(cfg.config_dir)
    notes: list[str] = []
    if cfg.board_path is None:
        board_path, n = find_input(cfg.raw_dir, bcfg)
        notes += n
    else:
        board_path = cfg.board_path
    if not board_path.exists():
        raise ProgressDataError(f"找不到看板檔案 {board_path.name}")
    board = load_board(board_path, bcfg)
    fatal = [i.problem for i in board.issues if i.row is None]
    if fatal or not board.rows:
        raise ProgressDataError(
            f"看板 {board_path.name} 無法正確讀取（{'；'.join(fatal) or '沒有任何案子'}），已停止"
        )
    board_date = board.board_date or cfg.as_of
    if board.board_date is None:
        notes.append(f"看板上沒有標示資料日期，以執行日 {cfg.as_of.isoformat()} 當作看板日期")

    mdir = cfg.meetings_dir or cfg.raw_dir / rules.folder
    files = sorted(p for p in mdir.glob("*") if p.is_file() and not p.name.startswith(("~$", ".")))
    if not files:
        raise ProgressDataError(f"{mdir} 裡沒有會議紀錄，請把紀錄（UTF-8 文字檔）放進去再跑")

    cases = [r["案子"] for r in board.rows]
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in board.rows:
        by_name[r["案子"]].append(r)
    aliases_path = cfg.aliases_path or PROJECT_ROOT / rules.aliases_file
    aliases, ignore, n, manual = _aliases(aliases_path, list(by_name))
    notes += n

    owners = {
        norm(x)
        for r in board.rows
        for x in re.split(r"[、／/（）()\s]+", str(r.get("負責人") or ""))
        if x.strip()
    }

    def names_case(text: str) -> bool:
        return bool(match_cases(text, cases, aliases, rules.generic_words))

    file_rows, used = [], []
    for p in files:
        if not fnmatch.fnmatch(p.name.lower(), rules.file_glob.lower()):
            file_rows.append(
                {
                    "檔案": p.name,
                    "會議日期": "",
                    "狀態": f"不是 {rules.file_glob} 檔，未使用",
                    "讀取行數": 0,
                    "略過行數（財務人事行政）": 0,
                }
            )
            continue
        m = parse_meeting(p, rules, names_case)
        ok, status = _file_status(m, board_date, max_age, cfg.as_of)
        file_rows.append(
            {
                "檔案": p.name,
                "會議日期": m.date.isoformat() if m.date else "待補",
                "狀態": status,
                "讀取行數": sum(1 for ln in m.lines if not ln.skipped) if ok else 0,
                "略過行數（財務人事行政）": sum(1 for ln in m.lines if ln.skipped) if ok else 0,
            }
        )
        if ok:
            used.append(m)

    mentions: dict[str, list[Mention]] = defaultdict(list)
    missing: dict[str, list[Mention]] = defaultdict(list)
    for m in used:
        case_ctx: set[str] = set()  # 標題或「名稱：」對到的案子，底下的條目屬於它
        new_ctx = ""  # 標題或「名稱：」對不到看板時，底下有日期的條目屬於這個名稱
        for ln in m.lines:
            men = Mention(m.path.name, ln.no, m.date, ln.exact, ln.approx, ln.stage_words)
            if ln.skipped:
                if ln.heading:
                    case_ctx, new_ctx = set(), ""
                elif ln.skipped == "word" and names_case(ln.text):
                    manual.append(
                        _manual(men, "這一行有財務、人事或行政字眼，系統未讀取，請看原文", set())
                    )
                continue
            hit = _match(ln, cases, aliases, rules)
            if ln.heading or (ln.label_only and not hit):
                case_ctx = hit if len(hit) == 1 else set()
                title = ln.label or ln.section
                # 正式標題（組別、段落）不是案名；短的標題或「名稱：」才可能是看板沒有的案子
                new_ctx = (
                    ""
                    if hit
                    or ln.heading == "strong"
                    or norm(title) in ignore
                    or _person_like(title, owners)
                    else title
                )
                if ln.label_only and not hit and norm(ln.label) not in ignore:
                    missing[ln.label].append(men)
                continue
            if ln.label_only:
                case_ctx, new_ctx = (hit if len(hit) == 1 else set()), ""
            target = hit or case_ctx
            if ln.unsure:
                manual.append(
                    _manual(men, f"年份不確定（{'、'.join(ln.unsure)}，可能是跨年），不猜", target)
                )
            if len(target) > 1:
                manual.append(_manual(men, "同一行對到多個案子，不猜是哪一案", target))
            elif len(target) == 1:
                name = next(iter(target))
                if len(by_name[name]) > 1:
                    manual.append(_manual(men, "看板上有同名的案子，請先把案名改成不同", target))
                else:
                    mentions[name].append(men)
            elif ln.label:
                if norm(ln.label) not in ignore:
                    missing[ln.label].append(men)
            elif new_ctx and (ln.exact or ln.approx or ln.stage_words):
                missing[new_ctx].append(men)
            elif ln.exact or ln.approx:
                manual.append(_manual(men, "有日期但對不到案子", set()))

    fill, diff = [], []
    for name, ms in mentions.items():
        row = by_name[name][0]
        stage = row.get("階段") or ""
        if stage in bcfg.done_stages:
            continue
        board_d = row.get("下一個日期")
        board_d = board_d if isinstance(board_d, dt.date) else None
        # 同一案在多份紀錄裡日期不同時，以最新一份紀錄為準（舊的可能已經延期）
        dated = [x for x in ms if any(d >= board_date for d in x.exact)]
        newest = max((x.meeting for x in dated), default=None)
        latest = sorted(
            {d for x in dated if x.meeting == newest for d in x.exact if d >= board_date}
        )
        future = latest + sorted({d for x in ms for d in x.exact if d >= board_date} - set(latest))
        approx = [a for x in ms for a in x.approx if a.end >= board_date]
        words = sorted({w for x in ms for w in x.words})
        where = "；".join(dict.fromkeys(x.where for x in ms))
        if board_d is None and (future or approx):
            fill.append(
                {
                    "案子": name,
                    "目前階段": stage,
                    "建議日期": future[0].isoformat() if future else "待補",
                    "其他提到的日期": _fmt(future[1:]),
                    "約略時程": _approx_text(approx),
                    "紀錄提到的階段字眼": "、".join(words),
                    "出處": where,
                }
            )
        reasons, board_side, meet_side = [], [], []
        if board_d is not None and latest and board_d not in latest:
            reasons.append("日期不同")
            board_side.append(board_d.isoformat())
            meet_side.append(_fmt(latest))
        done_words = [w for w in words if w in rules.done_words]
        # 洽談中、規劃中的案子可能是同一客戶的下一期，不算不一致
        if done_words and stage in bcfg.active_stages and stage != "結案中":
            reasons.append("紀錄寫結案，看板未結案")
            board_side.append(stage)
            meet_side.append("、".join(done_words))
        if reasons:
            diff.append(
                {
                    "案子": name,
                    "不一致": "；".join(reasons),
                    "看板": "；".join(board_side),
                    "會議紀錄": "；".join(meet_side),
                    "出處": where,
                    "建議": "以看板為準；若看板沒更新，請負責人確認後修改看板",
                }
            )
    miss_rows = [
        {
            "紀錄中的名稱": label,
            "提到的日期": _fmt(d for x in ms for d in x.exact),
            "約略時程": _approx_text(a for x in ms for a in x.approx),
            "紀錄提到的階段字眼": "、".join(sorted({w for x in ms for w in x.words})),
            "出處": "；".join(dict.fromkeys(x.where for x in ms)),
            "建議": "確認是否已結束或漏列；若是看板上的某一案，請加進案名對應表",
        }
        for label, ms in sorted(missing.items())
    ]
    fill.sort(key=lambda r: r["案子"])
    diff.sort(key=lambda r: r["案子"])

    meeting_files = [p for p in files if p.name in {m.path.name for m in used}]
    run_id = make_run_id("meetings", cfg.as_of, [board_path, *meeting_files, aliases_path])
    exact_n = sum(1 for r in fill if r["建議日期"] != "待補")
    headline = (
        f"會議紀錄可以幫看板補上 {len(fill)} 案的日期（{exact_n} 案有明確日期）；"
        f"{len(diff)} 案與看板不一致，{len(miss_rows)} 個名稱看板上沒有，{len(manual)} 項需要人工確認。"
    )
    bad_files = [r["檔案"] for r in file_rows if "未使用" in r["狀態"]]
    headline += "\n" + (
        f"有 {len(bad_files)} 份紀錄無法使用：{'、'.join(bad_files)}（見「會議紀錄清單」）。"
        if bad_files
        else "所有紀錄都讀得到。"
    )
    headline += f"\n看板資料日期 {board_date.isoformat()}；建議只是提醒，請確認後再更新看板，系統不會改動看板。"
    for n_ in notes:
        headline += "\n" + n_

    def df(rows: list[dict], cols: list[str]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=cols)

    sheets = {
        SHEETS[0]: df(
            fill,
            [
                "案子",
                "目前階段",
                "建議日期",
                "其他提到的日期",
                "約略時程",
                "紀錄提到的階段字眼",
                "出處",
            ],
        ),
        SHEETS[1]: df(diff, ["案子", "不一致", "看板", "會議紀錄", "出處", "建議"]),
        SHEETS[2]: df(
            miss_rows,
            ["紀錄中的名稱", "提到的日期", "約略時程", "紀錄提到的階段字眼", "出處", "建議"],
        ),
        SHEETS[3]: df(manual, ["出處", "日期", "原因", "可能的案子"]),
        SHEETS[4]: df(
            file_rows, ["檔案", "會議日期", "狀態", "讀取行數", "略過行數（財務人事行政）"]
        ),
    }
    footer = Footer(
        as_of=cfg.as_of,
        input_files=[board_path.name, *(p.name for p in meeting_files)],
        run_id=run_id,
        level=LEVEL,
        missing=[
            f"{r['案子']}：只有約略時程，沒有明確日期" for r in fill if r["建議日期"] == "待補"
        ],
        method=[
            f"會議紀錄比看板資料日期早超過 {max_age} 天的只存檔、不比對（待主管確認）；比看板新的紀錄一律比對。",
            "日期的年份＝會議那一年，該行寫「明年」時加一年；「9 月底」這類寫法列為約略時程，不換算成某一天。",
            "只採用看板資料日期當天或之後的日期；建議日期＝其中最早的一個。",
            "案名比對：先用案名對應表與完整案名，再用案名拆開後的關鍵字；對到多案時不猜，列入待人工確認。",
            "財務、人事、行政段落與相關項目不讀；輸出只有案名、日期、階段字眼與出處，不含紀錄原文。",
            "看板已完成的案子不提出建議；看板與紀錄不一致時以看板為準，只提醒。",
        ],
    )
    out = cfg.out_dir / f"看板補齊建議_{cfg.as_of.strftime('%Y%m%d')}.xlsx"
    write_xlsx(out, headline, sheets, footer)
    log = runlog.get_logger(run_id, cfg.log_dir)
    log.info("看板 %s；紀錄 %d 份，採用 %d 份", board_path.name, len(files), len(used))
    for r in file_rows:
        if "未使用" in r["狀態"]:
            log.warning("會議紀錄 %s：%s", r["檔案"], r["狀態"])
    runlog.close_logger(log)
    return BackfillResult(run_id, out, headline, notes)


def _match(ln: Line, cases, aliases, rules: MeetingRules) -> set[str]:
    # 先用「名稱：」的名稱比對；對不到時再用整行（例如「進度：某案 10/20」）
    hit = match_cases(ln.label, cases, aliases, rules.generic_words) if ln.label else set()
    return hit or match_cases(ln.text, cases, aliases, rules.generic_words)


def _person_like(title: str, owners: set[str]) -> bool:
    """標題像人名（看板負責人、純英文名、2–3 個中文字）時，不當成看板沒有的案子。"""
    t = norm(title)
    return t in owners or bool(
        re.fullmatch(r"[a-z]{2,15}", t) or re.fullmatch(r"[\u4e00-\u9fff]{2,3}", t)
    )


def _manual(men: Mention, why: str, cands: set[str]) -> dict:
    return {
        "出處": men.where,
        "日期": _fmt(men.exact) or _approx_text(men.approx),
        "原因": why,
        "可能的案子": "、".join(sorted(cands)),
    }
