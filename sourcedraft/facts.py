"""Step 1 fact sheet: schema, deterministic calculation, and consistency checks.

The LLM only *proposes* facts and calculation formulas. Every derived number
(sums, averages, ratios, YoY) is evaluated here in code, rounded with
ROUND_HALF_UP, and checked for caliber mismatches, abnormal swings and
past-year self-consistency before the drafting step ever sees it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

YOY_ALERT_THRESHOLD = 30.0  # percent, per v2 rule 2

GAP_TYPES = ["mandatory", "partial", "carried_over"]
CALC_KINDS = ["sum", "average", "ratio", "yoy", "consistency_check"]
ROUNDINGS = ["percent_1dp", "int", "1dp"]
ANOMALY_KINDS = ["數據矛盾", "數值異常", "異常波動", "單位不明", "口徑不一致", "往年不自洽"]

_NULLABLE_STR = {"type": "string"}

# JSON schema used with structured outputs for the Step 1 extraction call.
STEP1_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts", "calculations", "gaps", "anomalies", "outline", "new_initiatives"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label", "value", "unit", "period", "caliber", "source", "origin", "kind", "note"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "period": {"type": "string"},
                    "caliber": {"type": "string"},
                    "source": {"type": "string"},
                    "origin": {"type": "string", "enum": ["current_survey", "past_final"]},
                    "kind": {"type": "string", "enum": ["raw", "reported_derived"]},
                    "note": _NULLABLE_STR,
                },
            },
        },
        "calculations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label", "kind", "expression", "unit", "rounding", "caliber",
                             "anchor_basis", "reported_fact_id"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "kind": {"type": "string", "enum": CALC_KINDS},
                    "expression": {"type": "string"},
                    "unit": {"type": "string"},
                    "rounding": {"type": "string", "enum": ROUNDINGS},
                    "caliber": {"type": "string"},
                    "anchor_basis": {"type": "string"},
                    "reported_fact_id": {"type": "string"},
                },
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "type", "gri", "section_hint", "reason", "owner"],
                "properties": {
                    "item": {"type": "string"},
                    "type": {"type": "string", "enum": GAP_TYPES},
                    "gri": {"type": "string"},
                    "section_hint": {"type": "string"},
                    "reason": {"type": "string"},
                    "owner": {"type": "string"},
                },
            },
        },
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "kind", "detail"],
                "properties": {
                    "item": {"type": "string"},
                    "kind": {"type": "string", "enum": ANOMALY_KINDS},
                    "detail": {"type": "string"},
                },
            },
        },
        "outline": {"type": "array", "items": {"type": "string"}},
        "new_initiatives": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "detail", "source"],
                "properties": {
                    "name": {"type": "string"},
                    "detail": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        },
    },
}


class ExpressionError(ValueError):
    pass


_ALLOWED_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def safe_eval(expression: str, env: dict[str, Decimal] | None = None) -> Decimal:
    """Evaluate + - * / ( ) over numbers and identifiers, in Decimal. Nothing else."""
    env = env or {}
    expr = normalize_expression(expression)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"算式無法解析：{expression}") from exc

    def ev(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise ExpressionError(f"算式引用了不存在的 ID：{node.id}")
            return env[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ExpressionError(f"分母為 0：{expression}")
            return _ALLOWED_BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            val = ev(node.operand)
            return -val if isinstance(node.op, ast.USub) else val
        raise ExpressionError(f"算式含不允許的語法：{expression}")

    return ev(tree)


def normalize_expression(expression: str) -> str:
    """Accept the forms consultants write: 3,200 × 2 ÷ 4, full-width parens, etc."""
    expr = expression.strip()
    replacements = {"×": "*", "＊": "*", "÷": "/", "／": "/", "＋": "+", "－": "-", "−": "-",
                    "（": "(", "）": ")", "＝": "="}
    for src, dst in replacements.items():
        expr = expr.replace(src, dst)
    expr = re.sub(r"(?<=\d),(?=\d{3})", "", expr)  # thousands separators
    return expr


def quantize(value: Decimal, rounding: str) -> Decimal:
    if rounding == "int":
        return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fmt_number(value: Decimal | float | int, decimals: int | None = None) -> str:
    d = Decimal(str(value))
    if decimals is None:
        decimals = max(0, -d.normalize().as_tuple().exponent)
    q = d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return f"{q:,.{decimals}f}"


@dataclass
class CalcResult:
    id: str
    label: str
    kind: str
    expression: str
    numeric_expression: str
    raw: Decimal | None
    display: str
    unit: str
    caliber: str
    anchor: str
    error: str = ""


@dataclass
class Flag:
    kind: str
    item: str
    detail: str
    origin: str = "程式檢核"


@dataclass
class FactSheet:
    data: dict[str, Any]
    calcs: list[CalcResult] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)

    @property
    def facts(self) -> list[dict[str, Any]]:
        return self.data.get("facts", [])

    @property
    def gaps(self) -> list[dict[str, Any]]:
        return self.data.get("gaps", [])

    def known_numbers(self) -> set[str]:
        """All numbers (normalized strings) the draft may legitimately contain."""
        nums: set[str] = set()
        for f in self.facts:
            nums |= number_variants(Decimal(str(f["value"])))
        for c in self.calcs:
            if c.raw is not None:
                nums |= number_variants(c.raw)
                nums.add(normalize_num(c.display))
                nums.add(normalize_num(c.display).lstrip("+-"))
        return nums


def normalize_num(s: str) -> str:
    s = s.replace(",", "").replace("%", "").strip()
    try:
        d = Decimal(s)
    except Exception:
        return s
    d = d.normalize()
    return format(d, "f")


def number_variants(value: Decimal) -> set[str]:
    """A value may appear as-is or rounded to int/1dp/2dp (also as a percent of a ratio)."""
    out = {normalize_num(str(value))}
    for q in ("1", "0.1", "0.01"):
        out.add(normalize_num(str(value.quantize(Decimal(q), rounding=ROUND_HALF_UP))))
    return {o.lstrip("-") for o in out} | out


def compute(data: dict[str, Any]) -> FactSheet:
    """Evaluate every proposed calculation and run the v2 caliber/anomaly checks."""
    sheet = FactSheet(data=data)
    env: dict[str, Decimal] = {}
    facts_by_id: dict[str, dict[str, Any]] = {}
    for f in data.get("facts", []):
        env[f["id"]] = Decimal(str(f["value"]))
        facts_by_id[f["id"]] = f
    calibers: dict[str, str] = {fid: (f.get("caliber") or "") for fid, f in facts_by_id.items()}

    for c in data.get("calculations", []):
        numeric = _numeric_expression(c["expression"], env, facts_by_id)
        try:
            raw = safe_eval(c["expression"], env)
        except ExpressionError as exc:
            sheet.calcs.append(CalcResult(c["id"], c["label"], c["kind"], c["expression"], numeric, None,
                                          "", c.get("unit", ""), c.get("caliber", ""), "", error=str(exc)))
            sheet.flags.append(Flag("算式錯誤", c["label"], str(exc)))
            continue

        is_pct = c["kind"] in ("ratio", "yoy")
        shown = raw * 100 if is_pct else raw
        rounding = c.get("rounding") or ("percent_1dp" if is_pct else "int")
        if is_pct:
            rounding = "percent_1dp"
        q = quantize(shown, rounding)
        decimals = 0 if rounding == "int" else 1
        display = fmt_number(q, decimals) + ("%" if is_pct else "")
        if c["kind"] == "yoy" and q > 0:
            display = "+" + display
        env[c["id"]] = raw
        calibers[c["id"]] = c.get("caliber") or ""

        result_text = display if not is_pct else display
        formula = f"({numeric}) × 100%" if is_pct else numeric
        anchor = f"[依{c.get('anchor_basis') or '自收表'} 計算：{formula} = {result_text}]"
        res = CalcResult(c["id"], c["label"], c["kind"], c["expression"], numeric, raw, display,
                         c.get("unit", "") if not is_pct else "%", c.get("caliber", ""), anchor)
        sheet.calcs.append(res)

        if c["kind"] == "yoy" and abs(shown) > Decimal(str(YOY_ALERT_THRESHOLD)):
            sheet.flags.append(Flag("異常波動", c["label"],
                                    f"同比 {display}，超過 ±{YOY_ALERT_THRESHOLD:.0f}%，請確認數據或說明原因"))

        if c["kind"] == "yoy":
            ids = re.findall(r"[A-Za-z]\w*", c["expression"])
            cal = {calibers.get(i, "").strip() for i in ids if calibers.get(i, "").strip()
                   and calibers.get(i, "").strip() != "未註明"}
            if len(cal) > 1:
                sheet.flags.append(Flag("口徑不一致", c["label"],
                                        "同比兩端口徑不同：" + "／".join(sorted(cal)) + "，不得直接比較"))

        if c["kind"] == "consistency_check":
            rid = c.get("reported_fact_id") or ""
            reported = facts_by_id.get(rid)
            if reported is None:
                sheet.flags.append(Flag("算式錯誤", c["label"], f"consistency_check 找不到被驗算的 fact：{rid}"))
            else:
                rep = Decimal(str(reported["value"]))
                rep_decimals = max(0, -rep.normalize().as_tuple().exponent)
                recomputed = raw.quantize(Decimal(1).scaleb(-rep_decimals), rounding=ROUND_HALF_UP)
                if recomputed != rep:
                    sheet.flags.append(Flag(
                        "往年不自洽", reported["label"],
                        f"往年完稿宣稱 {fmt_number(rep)}，以原始數據重算 {numeric} = "
                        f"{fmt_number(recomputed, rep_decimals)}；同比請以重算值為準並註明"))
                    env[rid] = raw  # downstream YoY uses the verifiable figure

    for a in data.get("anomalies", []):
        sheet.flags.append(Flag(a["kind"], a["item"], a["detail"], origin="Step 1 判讀"))
    return sheet


def _numeric_expression(expression: str, env: dict[str, Decimal], facts: dict[str, dict]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(0)
        if key in facts and env.get(key) == Decimal(str(facts[key]["value"])):
            return fmt_number(Decimal(str(facts[key]["value"])))
        if key in env:
            v = env[key]
            return fmt_number(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP).normalize())
        return key

    out = re.sub(r"[A-Za-z]\w*", repl, normalize_expression(expression))
    return out.replace("*", " × ").replace("/", " ÷ ").replace("  ", " ")


def render_fact_sheet(sheet: FactSheet) -> str:
    lines = ["## 一、原始數值", "", "| ID | 項目 | 數值 | 單位 | 期間 | 口徑 | 出處 |", "| --- | --- | ---: | --- | --- | --- | --- |"]
    for f in sheet.facts:
        lines.append(f"| {f['id']} | {f['label']} | {fmt_number(Decimal(str(f['value'])))} | {f['unit']} | "
                     f"{f['period']} | {f['caliber']} | {f['source']} |")
    lines += ["", "## 二、衍生數值（程式計算，ROUND_HALF_UP）", "",
              "| ID | 項目 | 結果 | 口徑 | 建議錨點 |", "| --- | --- | ---: | --- | --- |"]
    for c in sheet.calcs:
        if c.error:
            lines.append(f"| {c.id} | {c.label} | 無法計算 | {c.caliber} | {c.error} |")
        else:
            unit = "" if c.unit == "%" else f" {c.unit}"
            lines.append(f"| {c.id} | {c.label} | {c.display}{unit} | {c.caliber} | `{c.anchor}` |")
    lines += ["", "## 三、程式檢核旗標", ""]
    if sheet.flags:
        lines += [f"- 【{f.kind}】{f.item}：{f.detail}（{f.origin}）" for f in sheet.flags]
    else:
        lines.append("- 無")
    lines += ["", "## 四、資料缺口", ""]
    if sheet.gaps:
        type_label = {"mandatory": "強制披露缺漏", "partial": "資料不完整", "carried_over": "沿用往年待確認"}
        for g in sheet.gaps:
            gri = f"（{g['gri']}）" if g.get("gri") else ""
            lines.append(f"- [{type_label.get(g['type'], g['type'])}] {g['item']}{gri}：{g['reason']}；"
                         f"對應小節：{g['section_hint']}；建議索取對象：{g['owner']}")
    else:
        lines.append("- 無")
    if sheet.data.get("new_initiatives"):
        lines += ["", "## 五、當年新增亮點", ""]
        lines += [f"- {n['name']}：{n['detail']}（{n['source']}）" for n in sheet.data["new_initiatives"]]
    if sheet.data.get("outline"):
        lines += ["", "## 六、往年完稿標題骨架", ""]
        lines += [f"- {h}" for h in sheet.data["outline"]]
    return "\n".join(lines)
