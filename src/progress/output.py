"""項目進度看板的輸出：進度看板 .xlsx、進度摘要 .md、summary.json。

輸出不含「卡點／風險」「備註」兩欄（系統根本不讀），資料等級維持「內部一般」。
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from progress.board import Board, BoardConfig
from progress.rules import RULE_NAMES, Evaluation
from shared.report import Footer, Section, md_escape, write_md, write_xlsx

MD_LIST_MAX = 10


def _method(th: dict, cfg: BoardConfig) -> list[str]:
    def v(k: str) -> str:
        return "未設定" if th.get(k) is None else str(th[k])

    return [
        f"P01（紅）：下一個日期早於今天，且階段不是{'、'.join(cfg.done_stages)}。",
        f"P02（黃）：下一個日期在今天起 {v('P02_due_soon_days')} 天內（含今天），且階段不是{'、'.join(cfg.done_stages)}（待主管確認）。",
        f"P03（紅）：階段是{'、'.join(cfg.blocked_stages)}。",
        f"P04（黃）：{'、'.join(cfg.active_stages)}的案子，連續 {v('P04_unchanged_days')} 天以上「階段、下一步、日期」都沒變（依歷次快照，待主管確認）。",
        f"P05（黃）：同一負責人負責的{'、'.join(cfg.active_stages)}案子超過 {v('P05_max_active_projects')} 個（待主管確認）。"
        "只算括號外的人名，「、」「／」分開的都算；非人名（如行政）不算。僅供排程參考，不是績效評估。",
        "每案燈號＝該案所有預警中最嚴重者；沒有預警為綠。",
        f"資料品質：{'、'.join(cfg.active_stages)}的案子沒有下一個日期或負責人、案名重複、日期錯誤、階段不在選單內；不計入預警。",
        f"不讀入、不輸出看板的「{'」「'.join(cfg.excluded_columns)}」欄（含客戶未公開資訊）。",
        "「近期下一步」只用來判斷有沒有變化（紀錄中只存雜湊），不輸出原文。",
    ]


def _quality_rows(board: Board, ev: Evaluation) -> list[dict]:
    names = {int(r["_row"]): r["案子"] for r in board.rows}
    rename = {"重複的 ID": "案名重複，無法和上週比較，請改成不同名稱", "案子": "客戶／案子"}
    rows = [
        {
            "來源列號": i.row,
            "案子": names.get(i.row),
            "欄位": rename.get(i.column, i.column),
            "問題": rename.get(i.problem, i.problem),
            "原始值": i.value,
        }
        for i in board.issues
    ]
    rows += [
        {"來源列號": q.row, "案子": q.project, "欄位": q.field, "問題": q.problem, "原始值": None}
        for q in ev.quality
    ]
    rows.sort(key=lambda x: (x["來源列號"] is None, x["來源列號"] or 0, x["欄位"] or ""))
    return rows


def _headline(data: dict) -> list[str]:
    m, alerts, ch = data["metrics"], data["alerts"], data["changes"]
    red, yellow = m["red_projects"], m["yellow_projects"]
    if red + yellow == 0:
        s1 = "本週沒有需要特別注意的案子。"
    else:
        red_rules = Counter(a["rule"] for a in alerts if a["level"] == "紅")
        parts = "、".join(f"{RULE_NAMES[r]} {n} 案" for r, n in sorted(red_rules.items()))
        s1 = (
            f"本週有 {red + yellow} 案需要注意：紅色 {red} 案"
            + (f"（{parts}）" if parts else "")
            + f"，黃色 {yellow} 案。"
        )
    owners = sum(1 for a in alerts if a["rule"] == "P05")
    if owners:
        s1 = s1[:-1] + f"；另有 {owners} 位負責人案數偏多。"
    if ch.get("available"):
        s2 = (
            f"與上次（{ch['prev_date']}）相比，新增 {len(ch['new'])} 項預警、解除 {len(ch['resolved'])} 項、"
            f"持續 {len(ch['ongoing'])} 項。"
        )
    else:
        s2 = "這是第一次執行，沒有上次的紀錄可比較。"
    miss = m["missing_next_date"]
    s3 = (
        f"另有 {miss} 案進行中卻沒有下一步日期，無法判斷是否延誤，請負責人補上。"
        if miss
        else "進行中的案子都有下一步日期。"
    )
    if data.get("board_note"):
        s3 = f"注意：{data['board_note']}。" + s3
    return [s1, s2, s3]


def _footer(data: dict, cfg: BoardConfig) -> Footer:
    return Footer(
        as_of=dt.date.fromisoformat(data["as_of"]),
        input_files=[data["input_file"]],
        run_id=data["run_id"],
        level=data["level"],
        missing=list(data["notes"]),
        method=_method(data["thresholds"], cfg),
    )


def _alert_df(alerts: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "燈號": a["level"],
                "規則": a["rule"],
                "規則說明": RULE_NAMES[a["rule"]],
                "案子／負責人": a["subject"],
                "為什麼": a["why"],
                "建議跟誰確認": a["suggested_owner"],
                "來源列號": a["row"],
            }
            for a in alerts
        ],
        columns=["燈號", "規則", "規則說明", "案子／負責人", "為什麼", "建議跟誰確認", "來源列號"],
    )


def _projects_df(board: Board, ev: Evaluation, cfg: BoardConfig, as_of: dt.date) -> pd.DataFrame:
    rules_by_row: dict[int, list[str]] = {}
    for a in ev.alerts:
        if a.row is not None:
            rules_by_row.setdefault(a.row, []).append(a.rule)
    order = {"紅": 0, "黃": 1, "綠": 2}
    rows = []
    for r in board.rows:
        row = int(r["_row"])
        d = r.get("下一個日期")
        if r.get("階段") in cfg.done_stages:
            days = "不適用"
        else:
            days = (d - as_of).days if d else None
        rows.append(
            {
                "來源列號": row,
                "案子": r["案子"],
                "類別": r.get("類別"),
                "階段": r.get("階段"),
                "負責人": r.get("負責人"),
                "下一個日期": d,
                "距今天數": days,
                "燈號": ev.lights[row],
                "觸發規則": "、".join(sorted(set(rules_by_row.get(row, [])))) or "無",
            }
        )
    rows.sort(key=lambda x: (order[x["燈號"]], x["來源列號"]))
    return pd.DataFrame(rows)


def _changes_df(ch: dict) -> pd.DataFrame:
    cols = ["變化", "燈號", "規則", "案子／負責人", "為什麼"]
    if not ch.get("available"):
        return pd.DataFrame([{"變化": "第一次執行，沒有上次紀錄可比較"}], columns=cols)
    rows = []
    for label, key in (("新增", "new"), ("解除", "resolved"), ("持續", "ongoing")):
        for a in ch[key]:
            rows.append(
                {
                    "變化": label,
                    "燈號": a["level"],
                    "規則": a["rule"],
                    "案子／負責人": a["subject"],
                    "為什麼": a["why"],
                }
            )
    for p in ch["added_projects"]:
        rows.append({"變化": "看板新增的案子", "案子／負責人": p, "為什麼": "上次沒有這個案名"})
    for p in ch["removed_projects"]:
        rows.append(
            {
                "變化": "看板上消失的案子",
                "案子／負責人": p,
                "為什麼": "上次有、這次沒有（可能改名或刪除）",
            }
        )
    if not rows:
        rows.append({"變化": "與上次相同，沒有變化"})
    return pd.DataFrame(rows, columns=cols)


def _owners_df(ev: Evaluation, th: dict) -> pd.DataFrame:
    n = th.get("P05_max_active_projects")
    return pd.DataFrame(
        [
            {
                "負責人": o,
                "進行中案數": len(ps),
                "是否超過門檻": "待補" if n is None else ("是" if len(ps) > n else "否"),
                "案子": "、".join(ps),
            }
            for o, ps in ev.owner_counts.items()
        ],
        columns=["負責人", "進行中案數", "是否超過門檻", "案子"],
    )


def _overview_df(data: dict) -> pd.DataFrame:
    m = data["metrics"]
    rows = [
        {"燈號": "紅", "說明": "需要立即確認的案子", "數量": m["red_projects"]},
        {"燈號": "黃", "說明": "需要留意的案子", "數量": m["yellow_projects"]},
        {"燈號": "綠", "說明": "沒有預警的案子", "數量": m["green_projects"]},
    ]
    count = Counter(a["rule"] for a in data["alerts"])
    rows += [
        {"燈號": "—", "說明": f"{r} {name}（預警筆數）", "數量": count.get(r, 0)}
        for r, name in RULE_NAMES.items()
    ]
    rows += [
        {"燈號": "—", "說明": "看板案子總數", "數量": m["total_projects"]},
        {"燈號": "—", "說明": "進行中的案子（含結案中、卡關）", "數量": m["active_projects"]},
        {"燈號": "—", "說明": "進行中卻沒有下一步日期", "數量": m["missing_next_date"]},
    ]
    return pd.DataFrame(rows, columns=["燈號", "說明", "數量"])


def write_xlsx_board(data, board, ev, cfg, out_dir: Path, as_of: dt.date) -> Path:
    sheets = {
        "預警清單": _alert_df(data["alerts"]),
        "項目明細": _projects_df(board, ev, cfg, as_of),
        "本週變化": _changes_df(data["changes"]),
        "負責人案數": _owners_df(ev, data["thresholds"]),
        "資料品質": pd.DataFrame(
            _quality_rows(board, ev), columns=["來源列號", "案子", "欄位", "問題", "原始值"]
        ),
    }
    return write_xlsx(
        out_dir / f"進度看板_{as_of.strftime('%Y%m%d')}.xlsx",
        "\n".join(_headline(data)),
        sheets,
        _footer(data, cfg),
        overview=_overview_df(data),
    )


def _md_table(rows: list[dict], cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {c: md_escape(r.get(c)) if isinstance(r.get(c), str) else r.get(c) for c in cols}
            for r in rows
        ],
        columns=cols,
    )


def write_md_summary(data, board, ev, cfg, out_dir: Path, as_of: dt.date) -> Path:
    head = _headline(data)
    sections: list[Section] = []
    alerts = [
        {
            "燈號": a["level"],
            "規則": RULE_NAMES[a["rule"]],
            "案子／負責人": a["subject"],
            "為什麼": a["why"],
            "建議跟誰確認": a["suggested_owner"],
        }
        for a in data["alerts"]
    ]
    if alerts:
        sections.append(
            Section(
                "需要注意的案子",
                [],
                _md_table(alerts, ["燈號", "規則", "案子／負責人", "為什麼", "建議跟誰確認"]),
            )
        )
    else:
        sections.append(Section("需要注意的案子", ["無。"]))
    ch = data["changes"]
    if ch.get("available"):
        rows = [{"變化": "新增", **a} for a in ch["new"]] + [
            {"變化": "解除", **a} for a in ch["resolved"]
        ]
        rows = [
            {
                "變化": r["變化"],
                "燈號": r["level"],
                "規則": RULE_NAMES[r["rule"]],
                "案子／負責人": r["subject"],
            }
            for r in rows
        ]
        paras = []
        if ch["removed_projects"]:
            paras.append(
                f"看板上消失的案子（可能改名或刪除）：{md_escape('、'.join(ch['removed_projects']))}"
            )
        sections.append(
            Section(
                "與上次相比",
                paras,
                _md_table(rows, ["變化", "燈號", "規則", "案子／負責人"]) if rows else None,
            )
        )
    else:
        sections.append(Section("與上次相比", [head[1]]))
    q = _quality_rows(board, ev)
    if q:
        shown = q[:MD_LIST_MAX]
        paras = [
            f"共 {len(q)} 項，不計入預警。"
            + (
                f"以下列前 {MD_LIST_MAX} 項，完整清單見 Excel「資料品質」分頁。"
                if len(q) > MD_LIST_MAX
                else ""
            )
        ]
        sections.append(
            Section("資料品質", paras, _md_table(shown, ["來源列號", "案子", "欄位", "問題"]))
        )
    else:
        sections.append(Section("資料品質", ["沒有發現問題。"]))
    return write_md(
        out_dir / f"進度摘要_{as_of.strftime('%Y%m%d')}.md",
        f"項目進度摘要（{as_of.isoformat()}）",
        md_escape(head[0]),
        [Section("本週結論", [md_escape(s) for s in head[1:]]), *sections],
        _footer(data, cfg),
    )


def write_summary(data: dict, out_dir: Path) -> Path:
    m, prev = data["metrics"], data.get("prev_metrics") or {}
    ref = f"{data['input_file']}（執行編號 {data['run_id']}）"

    def metric(key, field, label, unit="案"):
        return {
            "key": key,
            "label": label,
            "value": m[field],
            "unit": unit,
            "prev_value": prev.get(field),
            "source_ref": ref,
        }

    q = data["metrics"]["missing_next_date"]
    summary = {
        "system": "progress",
        "run_id": data["run_id"],
        "as_of": data["as_of"],
        "classification": data["level"],
        "headline": _headline(data)[0],
        "metrics": [
            metric("progress.red_alerts", "red_projects", "紅色預警項目數"),
            metric("progress.yellow_alerts", "yellow_projects", "黃色預警項目數"),
            metric("progress.active_projects", "active_projects", "進行中項目數"),
            metric("progress.missing_next_date", "missing_next_date", "進行中卻沒有下一步日期"),
        ],
        "alerts": [
            {
                "level": a["level"],
                "rule": a["rule"],
                "why": a["why"],
                "subject": a["subject"],
                "suggested_owner": a["suggested_owner"],
            }
            for a in data["alerts"]
        ],
        "data_quality": ([data["board_note"]] if data.get("board_note") else [])
        + ([f"{q} 案進行中卻沒有下一步日期"] if q else [])
        + list(data["notes"]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_all(data, board, ev, cfg, out_dir: Path, as_of: dt.date) -> dict[str, Path]:
    return {
        "xlsx": write_xlsx_board(data, board, ev, cfg, out_dir, as_of),
        "md": write_md_summary(data, board, ev, cfg, out_dir, as_of),
        "summary": write_summary(data, out_dir),
    }
