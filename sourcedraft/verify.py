"""Step 3 deterministic QA: re-check the draft before a consultant ever sees it.

Checks
  1. 計算錨點重算    every [依…計算：…] formula is re-evaluated and compared
  2. 數值溯源         every number in the body must exist in the inputs or the fact sheet
  3. 模式標記         internal keeps markers + appendix; client has none of them
  4. 附錄狀態         appendix status column only uses the four allowed values
  5. 缺口覆蓋         every Step 1 gap / program flag shows up in the draft
  6. 進位規則         percentages carry exactly one decimal
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .facts import ExpressionError, FactSheet, normalize_num, number_variants, safe_eval

ALLOWED_STATUS = {"待補件", "待複核", "口徑待確認", "數據矛盾"}
INTERNAL_MARKERS = [r"\[源自", r"\[沿用", r"\[依[^\]]*計算", r"【待顧問複核"]

CALC_MARKER = re.compile(r"\[依([^\]]*?)計算[：:]([^\]]*)\]")
ANY_MARKER = re.compile(r"\[(?:源自|沿用|依)[^\]]*\]|【[^】]*】|`[^`]*`")
NUMBER = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.,])[-+]?\d+(?:\.\d+)?")
PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")


@dataclass
class Finding:
    level: str  # error | warning | info
    check: str
    detail: str


@dataclass
class QAReport:
    mode: str
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def add(self, level: str, check: str, detail: str) -> None:
        self.findings.append(Finding(level, check, detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def to_dict(self) -> dict:
        return {"mode": self.mode, "stats": self.stats, "findings": [asdict(f) for f in self.findings]}

    def to_markdown(self) -> str:
        icon = {"error": "❌ 錯誤", "warning": "⚠️ 警示", "info": "ℹ️ 資訊"}
        lines = ["# 溯稿 Step 3 自動檢核報告", "",
                 f"- 輸出模式：{self.mode}",
                 f"- 錯誤：{len(self.errors)}　警示：{len(self.warnings)}"]
        lines += [f"- {k}：{v}" for k, v in self.stats.items()]
        lines += ["", "| 等級 | 檢核項目 | 說明 |", "| --- | --- | --- |"]
        if not self.findings:
            lines.append("| ✅ | 全部通過 | 無 |")
        order = {"error": 0, "warning": 1, "info": 2}
        for f in sorted(self.findings, key=lambda f: order[f.level]):
            lines.append(f"| {icon[f.level]} | {f.check} | {f.detail.replace('|', '｜')} |")
        lines += ["", "> 本報告由程式產生，僅檢核可機械驗證的項目。事實、數據、專有名詞、揭露要求仍須顧問逐項確認（作業手冊 05-4）。"]
        return "\n".join(lines)


def split_appendix(draft: str) -> tuple[str, str]:
    m = re.search(r"^#{1,6}\s*(附錄|客戶補件清單)", draft, flags=re.M)
    if not m:
        return draft, ""
    return draft[: m.start()], draft[m.start():]


def _source_numbers(text: str) -> set[str]:
    out: set[str] = set()
    for m in NUMBER.finditer(text):
        out.add(normalize_num(m.group(0)).lstrip("+-"))
    return out


def _parse_num(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def verify(draft: str, mode: str, sources_text: str, sheet: FactSheet | None = None) -> QAReport:
    report = QAReport(mode=mode)
    body, appendix = split_appendix(draft)

    _check_calc_markers(body, report)
    _check_traceability(body, sources_text, sheet, report)
    _check_percent_rounding(body, _source_numbers(sources_text), report)
    if mode == "client":
        _check_client(draft, appendix, report)
    else:
        _check_internal(body, appendix, sheet, report)
    if sheet is not None:
        _check_gap_coverage(draft, appendix, mode, sheet, report)
    return report


def _check_calc_markers(body: str, report: QAReport) -> None:
    count = 0
    for m in CALC_MARKER.finditer(body):
        count += 1
        content = m.group(2).replace("＝", "=")
        formula, _, stated = content.rpartition("=")
        if not formula:
            formula, stated = content, ""
        is_pct = "%" in stated
        stated_val = _parse_num(re.sub(r"[^\d.,+\-]", "", stated)) if re.search(r"\d", stated) else None
        if stated_val is None:  # fall back to the number written just before the marker
            before_text = body[max(0, m.start() - 80): m.start()]
            before = NUMBER.findall(before_text)
            stated_val = _parse_num(before[-1]) if before else None
            is_pct = bool(before) and bool(re.search(re.escape(before[-1]) + r"\s*%", before_text))
        clean = formula.replace("100%", "100").replace("％", "%")
        clean = re.sub(r"[^\d.,+\-×÷*/()（）\s]", " ", clean)
        try:
            computed = safe_eval(clean)
        except ExpressionError:
            report.add("warning", "計算錨點重算", f"算式無法自動驗算，請人工確認：{m.group(0)}")
            continue
        if stated_val is None:
            report.add("warning", "計算錨點重算", f"找不到算式對應的結果數值：{m.group(0)}")
            continue
        decimals = max(0, -stated_val.normalize().as_tuple().exponent)
        quant = Decimal(1).scaleb(-decimals)
        target = stated_val.quantize(quant).copy_abs()
        candidates = [computed, computed * 100] if is_pct else [computed]
        if not any(c.quantize(quant, rounding=ROUND_HALF_UP).copy_abs() == target for c in candidates):
            report.add("error", "計算錨點重算",
                       f"{m.group(0)} 重算為 {computed.quantize(Decimal('0.0001'))}，與文中數值 {stated_val} 不符")
    report.stats["計算錨點數"] = count


def _check_traceability(body: str, sources_text: str, sheet: FactSheet | None, report: QAReport) -> None:
    known = _source_numbers(sources_text)
    if sheet is not None:
        known |= sheet.known_numbers()
    for m in CALC_MARKER.finditer(body):  # numbers a verified calc marker produced
        for n in NUMBER.findall(m.group(2)):
            known |= number_variants(_parse_num(n) or Decimal(0))
    text = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    text = ANY_MARKER.sub(" ", text)
    text = re.sub(r"GRI\s*\d+(?:-\d+)?", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+){2,}\b", " ", text)  # section numbers 3.2.1
    untraced: list[str] = []
    seen = 0
    for m in NUMBER.finditer(text):
        raw = m.group(0)
        norm = normalize_num(raw).lstrip("+-")
        if re.fullmatch(r"(19|20)\d{2}", norm):  # years
            continue
        seen += 1
        if norm not in known and raw not in untraced:
            untraced.append(raw)
    report.stats["正文數值數"] = seen
    for raw in untraced:
        report.add("warning", "數值溯源", f"正文數值「{raw}」在輸入物料與事實表中都找不到，請確認非杜撰")


def _check_percent_rounding(body: str, source_numbers: set[str], report: QAReport) -> None:
    """Derived percentages need one decimal; a percentage the client reported verbatim is left as given."""
    text = ANY_MARKER.sub(" ", body)
    bad = sorted({m.group(1) for m in PERCENT.finditer(text)
                  if len(m.group(1).partition(".")[2]) != 1 and normalize_num(m.group(1)) not in source_numbers})
    for b in bad:
        report.add("warning", "進位規則", f"百分比「{b}%」未統一至小數點後一位")


def _check_client(draft: str, appendix: str, report: QAReport) -> None:
    for pat in INTERNAL_MARKERS:
        hits = re.findall(pat + r"[^\]】]*[\]】]?", draft)
        for h in hits[:5]:
            report.add("error", "模式標記", f"client 版殘留內部標記：{h}")
    if re.search(r"^#{1,6}\s*附錄[：:]?\s*本章顧問", draft, flags=re.M):
        report.add("error", "模式標記", "client 版不得輸出顧問附錄")
    if not re.search(r"客戶補件清單", draft):
        report.add("warning", "模式標記", "client 版缺少「客戶補件清單」")
    report.stats["待客戶補充處"] = len(re.findall(r"【待客戶補充", draft))


def _appendix_rows(appendix: str) -> list[list[str]]:
    rows = []
    for line in appendix.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.fullmatch(r"\|[\s:\-|]+\|?", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] in ("序號", "#"):
            continue
        rows.append(cells)
    return rows


def _check_internal(body: str, appendix: str, sheet: FactSheet | None, report: QAReport) -> None:
    if not appendix:
        report.add("error", "附錄狀態", "internal 版缺少「附錄：本章顧問審校與待補件清單」")
        return
    rows = _appendix_rows(appendix)
    report.stats["附錄列數"] = len(rows)
    for r in rows:
        status = r[2] if len(r) > 2 else ""
        if status not in ALLOWED_STATUS:
            report.add("error", "附錄狀態", f"第 {r[0]} 列狀態「{status}」不在限用值（{'／'.join(sorted(ALLOWED_STATUS))}）")
    flags_in_body = re.findall(r"【待顧問複核[^】]*】", body)
    distinct = len(set(flags_in_body))
    report.stats["正文待複核標記"] = len(flags_in_body)
    if distinct > len(rows):
        report.add("warning", "附錄狀態", f"正文有 {distinct} 種不同的【待顧問複核】，附錄只有 {len(rows)} 列，可能漏列")
    if not re.search(r"\[源自", body):
        report.add("error", "模式標記", "internal 版正文沒有任何 [源自…] 溯源錨點")
    if sheet is not None:
        for f in sheet.flags:
            if f.item and f.item not in body + appendix and f.kind not in body + appendix:
                report.add("warning", "缺口覆蓋", f"程式檢核旗標未反映在稿件中：【{f.kind}】{f.item}")


def _check_gap_coverage(draft: str, appendix: str, mode: str, sheet: FactSheet, report: QAReport) -> None:
    if mode == "client":  # the client checklist carries no GRI codes; compare counts instead
        rows = _appendix_rows(appendix)
        needed = len(sheet.gaps)
        report.stats["客戶補件清單列數"] = len(rows)
        if len(rows) < needed:
            report.add("warning", "缺口覆蓋", f"Step 1 共有 {needed} 個資料缺口，客戶補件清單只有 {len(rows)} 列")
        return
    compact = re.sub(r"\s", "", draft)
    for g in sheet.gaps:
        gri = re.sub(r"\s", "", g.get("gri") or "")
        if gri and gri not in compact:
            report.add("warning", "缺口覆蓋", f"資料缺口「{g['item']}」對應的 {g['gri']} 未出現在稿件中")
