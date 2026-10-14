"""把各系統的摘要組成一頁週報的內容（不寫檔）。數字一律原樣取自 summary.json。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from digest.sources import NOT_LAUNCHED, DigestConfig, SystemInput
from shared.classify import Classifier

DASH = "—"


def _safe_url(u: object) -> bool:
    if not isinstance(u, str) or not u or any(ch.isspace() or ch in "<>[]\"'`" for ch in u):
        return False
    parts = urlsplit(u)
    # 不接受「帳號@網域」的寫法（看起來像 A 網站，實際連到 B 網站）
    return parts.scheme in ("http", "https") and bool(parts.hostname) and "@" not in parts.netloc


def _short(t: object, n: int = 120) -> str:
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[: n - 1] + "…"


LINE_CHARS = 50  # 一頁 A4、9.5 號字，一行約 50 個中文字
LABEL_MAX = 16  # 指標名稱最多幾個字（表格欄位窄，一格約 9 字換行，最多兩行）
UNIT_MAX = 6


@dataclass
class MetricRow:
    label: str
    this: str
    prev: str
    change: str
    unit: str
    key: str = ""
    raw_value: object = None  # 供測試核對：原樣取自 summary.json


@dataclass
class Digest:
    as_of: dt.date
    period_start: dt.date
    level: str
    sentences: list[str]
    metrics: list[MetricRow]
    decisions: list[str]
    decisions_more: int
    intel: list[dict]
    intel_note: str | None
    data_quality: list[str]
    data_quality_more: int
    input_refs: list[str]
    missing: list[str] = field(default_factory=list)
    method: list[str] = field(default_factory=list)
    run_id: str = ""
    systems: dict = field(default_factory=dict)  # 各系統本週狀態，給其他出口判斷資料是否為本週

    def body_size(self, line_chars: int = LINE_CHARS) -> int:
        """估算版面：每段依實際換行占幾行，再換算成字數（短的一行也算一整行）。"""
        size = 0
        for m in self.metrics:  # 表格每列依最寬的一格換行數計
            rows = max(1, -(-len(m.label) // 9), -(-len(m.this) // 9), -(-len(m.unit) // 5))
            size += rows * line_chars
        paras = list(self.sentences)
        paras += (
            self.decisions + [f"{i['title']} {i['url']}" for i in self.intel] + self.data_quality
        )
        paras += [self.intel_note] if self.intel_note else []
        paras += ["（其餘…）"] * (bool(self.decisions_more) + bool(self.data_quality_more))
        return size + sum(max(1, -(-len(p) // line_chars)) * line_chars for p in paras)

    def body_text(self) -> str:
        parts = list(self.sentences)
        parts += [f"{m.label} {m.this} {m.prev} {m.change} {m.unit}" for m in self.metrics]
        parts += self.decisions + [f"{i['title']} {i['url']}" for i in self.intel]
        parts += self.data_quality + ([self.intel_note] if self.intel_note else [])
        return "\n".join(parts)


def _plain(d: Decimal) -> str:
    """不用科學記號；極大或極小的數字才維持原樣。"""
    if d != 0 and (abs(d) >= Decimal("1e15") or abs(d) < Decimal("1e-6")):
        return str(d)
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmt_value(v: object) -> str:
    if v is None:
        return "待補"
    if isinstance(v, float):
        return _plain(Decimal(str(v)))
    return str(v)


def fmt_change(v: object, prev: object) -> str:
    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    if not num(v) or not num(prev):
        return "待補"
    try:
        d = Decimal(str(v)) - Decimal(str(prev))
    except InvalidOperation:
        return "待補"
    if not d.is_finite():
        return "待補"
    if d == 0:
        return "持平"
    return f"+{_plain(d)}" if d > 0 else f"−{_plain(-d)}"


def _metric_rows(inputs: list[SystemInput], metric_cfg: list[dict]) -> list[MetricRow]:
    by_key = {s.cfg.key: s for s in inputs}
    rows: list[MetricRow] = []
    shown_not_launched: set[str] = set()
    for m in metric_cfg:
        m = {**m, "label": _short(m["label"], LABEL_MAX)}
        system = by_key.get(m["system"])
        if system is None:
            rows.append(
                MetricRow(m["label"], "待補（週報設定沒有這個系統）", DASH, DASH, "", m["key"])
            )
            continue
        if system.status == NOT_LAUNCHED:
            if system.cfg.key not in shown_not_launched:
                shown_not_launched.add(system.cfg.key)
                rows.append(
                    MetricRow(f"{system.cfg.name}指標", "系統尚未上線", DASH, DASH, "", m["key"])
                )
            continue
        if not system.ok:
            rows.append(MetricRow(m["label"], system.status_text, DASH, DASH, "", m["key"]))
            continue
        found = next((x for x in system.summary.metrics if x.key == m["key"]), None)
        if found is None:
            rows.append(
                MetricRow(m["label"], "待補（摘要檔沒有這個指標）", DASH, DASH, "", m["key"])
            )
            continue
        rows.append(
            MetricRow(
                m["label"],
                fmt_value(found.value),
                fmt_value(found.prev_value),
                fmt_change(found.value, found.prev_value),
                _short(found.unit, UNIT_MAX),
                m["key"],
                found.value,
            )
        )
    return rows


def build(
    inputs: list[SystemInput],
    metric_cfg: list[dict],
    dcfg: DigestConfig,
    as_of: dt.date,
    metrics_status: str | None,
    stale_days: int | None,
) -> Digest:
    launched = [s for s in inputs if s.status != NOT_LAUNCHED]
    not_launched = [s for s in inputs if s.status == NOT_LAUNCHED]
    ok = [s for s in launched if s.ok]

    # 資料等級：讀得到的摘要檔中最高者；一份都沒有時，依規定當作最嚴格
    level = Classifier().highest(
        [s.summary.classification for s in inputs if s.summary is not None]
    )

    # 結論：已上線系統各一句（直接用 headline），不足三句時補一句狀態句
    lines = []
    for s in launched:
        if s.ok:
            lines.append(f"{s.cfg.name}：{s.summary.headline}")
        else:
            lines.append(f"{s.cfg.name}：{s.status_text}（{s.reason}）。")
    dq_all: list[str] = [
        f"［{s.cfg.name}］{s.status_text}：{s.reason}" for s in launched if not s.ok
    ]
    for s in ok:
        dq_all += [f"［{s.cfg.name}］{x}" for x in s.summary.data_quality]
    if len(lines) < 3:
        parts = [f"{s.cfg.name}尚未上線" for s in not_launched]
        parts += [f"{s.cfg.name}本週未更新" for s in launched if not s.ok]
        n_dq = sum(len(s.summary.data_quality) for s in ok)
        if n_dq:
            parts.append(f"各系統共有 {n_dq} 項資料品質提醒（見最後一節）")
        status = (
            "；".join(parts) + "。" if parts else "所有已上線系統本週都已更新，沒有資料品質提醒。"
        )
        lines.append(status)
    sentences = lines[:3]

    # 需要您決定的事項：紅色預警，依系統順序
    bad_levels = [
        f"［{s.cfg.name}］有 {n} 條預警的燈號不是「紅」或「黃」，未列入，請檢查該系統"
        for s in ok
        if (n := sum(1 for a in s.summary.alerts if a.level not in ("紅", "黃")))
    ]
    dq_all += bad_levels
    for s in ok:
        keys = [m.key for m in s.summary.metrics]
        dups = sorted({k for k in keys if keys.count(k) > 1})
        if dups:
            dq_all.append(
                f"［{s.cfg.name}］指標 {'、'.join(dups)} 重複出現，週報採用第一筆，請檢查該系統"
            )
    # 紅色預警拆成（開頭、原因、建議窗口），截短時只截原因，保留建議跟誰確認
    red_parts = [
        (
            f"［{s.cfg.name}］{_short(a.subject, 30)}：",
            a.why,
            f" → 建議跟 {_short(a.suggested_owner, 20)} 確認" if a.suggested_owner else "",
        )
        for s in ok
        for a in s.summary.alerts
        if a.level == "紅"
    ]
    reds = [h + w + t for h, w, t in red_parts]

    # 外部情報前幾則
    intel_in = next((s for s in inputs if s.cfg.key == "intel"), None)
    intel_items: list[dict] = []
    intel_note = None
    if intel_in is None or intel_in.status == NOT_LAUNCHED:
        intel_note = "外部情報系統尚未上線。"
    elif not intel_in.ok:
        intel_note = f"外部情報{intel_in.status_text}。"
    else:
        raw = intel_in.extra.get("highlights", [])
        raw = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []
        intel_items = [
            {"title": _short(h.get("title")), "url": str(h["url"])}
            for h in raw
            if isinstance(h.get("title"), str)
            and h.get("title").strip()
            and _safe_url(h.get("url"))
        ]
        if len(intel_items) < len(raw):
            dq_all.append(
                f"［{intel_in.cfg.name}］有 {len(raw) - len(intel_items)} 則情報缺標題或連結不是 http／https，未列出"
            )
        if not intel_items:
            intel_note = "本期無符合項目。"

    # 一頁限制：依序截短資料品質 → 外部情報 → 需要決定的事項
    n_dq, n_intel, n_dec = dcfg.data_quality_max, dcfg.intel_max, dcfg.decisions_max
    missing: list[str] = []

    def make(cap: int | None = None) -> Digest:
        """cap：條數縮到最少仍太長時，每條文字最多幾個字。"""

        def cut(items: list[str]) -> list[str]:
            return [_short(x, cap) for x in items] if cap else items

        return Digest(
            as_of=as_of,
            period_start=as_of - dt.timedelta(days=6),
            level=level,
            sentences=cut(sentences) if cap and cap < 100 else sentences,
            metrics=_metric_rows(inputs, metric_cfg),
            decisions=[
                h + (_short(w, max(10, cap - len(h) - len(t))) if cap else w) + t
                for h, w, t in red_parts[:n_dec]
            ],
            decisions_more=max(0, len(reds) - n_dec),
            intel=[
                {**i, "title": _short(i["title"], cap)} if cap else i for i in intel_items[:n_intel]
            ],
            intel_note=intel_note,
            data_quality=cut(dq_all[:n_dq]),
            data_quality_more=max(0, len(dq_all) - n_dq),
            input_refs=[
                f"{s.cfg.key}/summary.json（{s.summary.run_id}）"
                for s in inputs
                if s.summary is not None
            ],
        )

    d = make()
    while d.body_size() > dcfg.max_chars and (n_dq > 1 or n_intel > 1 or n_dec > 1):
        if n_dq > 1:
            n_dq -= 1
        elif n_intel > 1:
            n_intel -= 1
        else:
            n_dec -= 1
        d = make()
    for cap in (100, 60, 45):
        if d.body_size() <= dcfg.max_chars:
            break
        d = make(cap)
    if d.body_size() > dcfg.max_chars:
        missing.append(f"內文仍超過 {dcfg.max_chars} 字上限，請主管確認是否放寬")

    for s in not_launched:
        missing.append(f"{s.cfg.name}：系統尚未上線")
    for s in launched:
        if not s.ok:
            missing.append(f"{s.cfg.name}：{s.status_text}（{s.reason}）")
    if intel_in is not None and intel_in.ok and intel_in.extra.get("mock_summary"):
        missing.append("外部情報摘要仍為模擬版（週報只列標題與連結）")
    for s in inputs:
        if s.summary is not None and s.summary.classification not in Classifier().levels:
            missing.append(
                f"{s.cfg.name}的資料等級「{s.summary.classification}」不認得，已當作客戶機密"
            )
    long_labels = [m["key"] for m in metric_cfg if len(m["label"]) > LABEL_MAX]
    if long_labels:
        more = "…" if len(long_labels) > 3 else ""
        missing.append(
            f"{len(long_labels)} 個指標名稱超過 {LABEL_MAX} 字已截短（{'、'.join(long_labels[:3])}{more}），"
            "請在 config/metrics.yaml 改短"
        )
    if stale_days is None:
        missing.append("「本週未更新」的天數門檻未設定，不判斷摘要是否過期")
    if metrics_status:
        missing.append(f"指標清單為起始版，{metrics_status}")
    d.missing = [_short(x, 90) for x in missing]  # 頁尾每條提醒限長，避免撐出第二頁
    d.method = [
        "數字原樣取自各系統 summary.json，不重新計算；變化＝本週－上週，上週無值寫「待補」。",
        "結論引用各系統結論句；決定事項＝各系統紅色預警；資料等級＝讀到的摘要中最高者；不使用大模型。",
        f"摘要檔超過 {stale_days if stale_days is not None else '（未設定）'} 天沒更新標「本週未更新」（待主管確認）。",
    ]
    return d
