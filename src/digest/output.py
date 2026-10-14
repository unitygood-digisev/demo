"""管理層週報的三種輸出：Word（一頁）、Markdown、郵件純文字版。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from digest.build import Digest
from shared.report import LEVEL_BANNER, Footer, Section, md_escape, write_docx, write_md

METRIC_COLS = ["指標", "本週", "上週", "變化", "單位"]


def _title(d: Digest) -> str:
    return f"管理層週報（{d.period_start.isoformat()}～{d.as_of.isoformat()}）"


def _footer(d: Digest) -> Footer:
    return Footer(
        as_of=d.as_of,
        input_files=d.input_refs,
        run_id=d.run_id or f"digest-{d.as_of.strftime('%Y%m%d')}",
        level=d.level,
        missing=d.missing,
        method=d.method,
    )


def _sections(d: Digest, esc) -> list[Section]:
    metrics = pd.DataFrame(
        [
            {
                "指標": esc(m.label),
                "本週": esc(m.this),
                "上週": esc(m.prev),
                "變化": m.change,
                "單位": esc(m.unit) or "—",
            }
            for m in d.metrics
        ],
        columns=METRIC_COLS,
    )
    decisions = [f"・{esc(x)}" for x in d.decisions] or ["本週沒有紅色預警。"]
    if d.decisions_more:
        decisions.append(f"（其餘 {d.decisions_more} 條紅色預警，見各系統報表）")
    link = (lambda u: f"<{u}>") if esc is md_escape else (lambda u: u)  # noqa: E731
    intel = [f"・{esc(i['title'])}　{link(i['url'])}" for i in d.intel]
    if d.intel_note:
        intel.append(esc(d.intel_note))
    dq = [f"・{esc(x)}" for x in d.data_quality] or ["沒有資料品質提醒。"]
    if d.data_quality_more:
        dq.append(f"（其餘 {d.data_quality_more} 項，見各系統報表）")
    return [
        Section("關鍵指標（本週／上週／變化）", [], metrics),
        Section("需要您決定的事項", decisions),
        Section("外部情報", intel),
        Section("資料品質提醒", dq),
    ]


def write_all(d: Digest, out_dir: Path) -> dict[str, Path]:
    stem = d.as_of.strftime("%Y%m%d")
    plain = lambda x: x  # noqa: E731
    docx = write_docx(
        out_dir / f"管理層週報_{stem}.docx",
        _title(d),
        "\n".join(f"{i}. {s}" for i, s in enumerate(d.sentences, 1)),
        _sections(d, plain),
        _footer(d),
        compact=True,
    )
    md = write_md(
        out_dir / f"管理層週報_{stem}.md",
        _title(d),
        "  \n".join(f"{i}\\. {md_escape(s)}" for i, s in enumerate(d.sentences, 1)),
        _sections(d, md_escape),
        _footer(d),
    )
    txt = out_dir / f"管理層週報_郵件版_{stem}.txt"
    txt.write_text(to_text(d), encoding="utf-8")
    js = out_dir / f"管理層週報_資料_{stem}.json"
    js.write_text(json.dumps(to_data(d), ensure_ascii=False, indent=1), encoding="utf-8")
    return {"docx": docx, "md": md, "txt": txt, "json": js}


def to_data(d: Digest) -> dict:
    """週報內容的結構化版本，給 Google 試算表同步等其他出口使用（不重新計算）。"""
    return {
        "as_of": d.as_of.isoformat(),
        "period_start": d.period_start.isoformat(),
        "title": _title(d),
        "level": d.level,
        "level_banner": LEVEL_BANNER.get(d.level, d.level),
        "run_id": d.run_id,
        "sentences": d.sentences,
        "metrics": [
            {
                "key": m.key,
                "label": m.label,
                "this": m.this,
                "prev": m.prev,
                "change": m.change,
                "unit": m.unit,
            }
            for m in d.metrics
        ],
        "decisions": d.decisions,
        "decisions_more": d.decisions_more,
        "intel": d.intel,
        "intel_note": d.intel_note,
        "data_quality": d.data_quality,
        "data_quality_more": d.data_quality_more,
        "footer": _footer(d).lines(),
        "systems": d.systems,
    }


def to_text(d: Digest) -> str:
    """可直接貼到郵件內文的純文字版。"""
    f = _footer(d)
    out = [f"【{LEVEL_BANNER.get(d.level, d.level)}】{_title(d)}", "", "本週結論"]
    out += [f"{i}. {s}" for i, s in enumerate(d.sentences, 1)]
    out += ["", "關鍵指標（本週／上週／變化）"]
    out += [
        f"- {m.label}：{m.this}／{m.prev}／{m.change}" + (f"（{m.unit}）" if m.unit else "")
        for m in d.metrics
    ]
    for sec in _sections(d, lambda x: x)[1:]:
        out += ["", sec.title] + [p.replace("・", "- ", 1) for p in sec.paragraphs]
    out += ["", "—"] + f.lines()
    return "\n".join(out) + "\n"
