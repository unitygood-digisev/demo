"""永續情資日報：把當天的情報整理成副執行長要的版面（HTML 郵件＋純文字備份）。

版面依副執行長 2026-10-15 修訂版與 2026-10-19 版面設計：
刊頭 → 今日一句話 → 今日要點 → 重要程度 5、4 的新聞 → 閱讀方式 → 主題索引 → 主題情資 → 說明。

這一版全部由規則產生，不用大模型：
- 「今日一句話」「今日要點」只用則數、標題與來源自帶的簡介組成，不加研判。
- 「主題觀點」「對優樂地的意涵」「商機與行動雷達」「近期重要日程」需要研判，資料有給才顯示
  （之後接上大模型或由研究團隊填寫）；沒有就整段不出現，不放空殼。
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shared.config import load_yaml

WEEKDAY = "一二三四五六日"
INK, MUTED, LINE, BRAND, BRAND2, PAPER = (
    "#1F2A27",
    "#6B7570",
    "#DDE5E1",
    "#1F5C4A",
    "#2E7D5B",
    "#FFFFFF",
)
SOFT = "#F3F7F5"


def wd(d: dt.date) -> str:
    return f"{d.isoformat()}（週{WEEKDAY[d.weekday()]}）"


def short(d: dt.date) -> str:
    return f"{d.month}/{d.day}（{WEEKDAY[d.weekday()]}）"


@dataclass
class Catalog:
    title: str
    subtitle: str
    audience: str
    categories: list[dict]
    topics: list[dict]
    importance: dict[int, str]
    key_points: int = 4

    @classmethod
    def load(cls, config_dir: Path | None = None, name: str = "brief.yaml") -> Catalog:
        c = load_yaml(name, config_dir)
        return cls(
            title=c["title"],
            subtitle=c["subtitle"],
            audience=c["audience"],
            categories=list(c["categories"]),
            topics=list(c["topics"]),
            importance={int(k): str(v) for k, v in (c.get("importance") or {}).items()},
            key_points=int(c.get("key_points", 4)),
        )


@dataclass
class Brief:
    as_of: dt.date
    start: dt.date
    level: str
    run_id: str
    catalog: Catalog
    categories: list[dict] = field(default_factory=list)  # [{id,name,color,topics:[...]}]
    points: list[dict] = field(default_factory=list)
    key_items: list[dict] = field(default_factory=list)
    headline: str = ""
    notes: list[str] = field(default_factory=list)
    total: int = 0
    empty: int = 0
    more: int = 0  # 超過每主題上限而沒列出的則數
    radar: list[list[str]] = field(default_factory=list)  # 研判，有給才顯示
    schedule: list[list[str]] = field(default_factory=list)  # 研判，有給才顯示

    @property
    def topic_count(self) -> int:
        return sum(len(c["topics"]) for c in self.categories)


def keyword_lines(keywords_path: Path) -> dict[str, str]:
    """每個主題的關鍵字顯示文字（取自關鍵字檔；本機版含客戶名稱，所以只出現在本機產出）。"""
    try:
        data = yaml.safe_load(keywords_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, list[str]] = {}
    for k in data.get("keywords") or []:
        if not isinstance(k, dict) or k.get("單獨不算"):
            continue
        topic = str(k.get("主題") or k.get("詞") or "").strip()
        terms = [str(k.get("詞"))] + [str(x) for x in (k.get("同義詞") or [])]
        out.setdefault(topic, [])
        out[topic] += [t for t in terms if t not in out[topic]]
    return {t: "、".join(v) for t, v in out.items()}


def build(
    day: dict,
    catalog: Catalog,
    start: dt.date,
    per_topic: int | None,
    keywords_path: Path | None = None,
    extras: dict | None = None,
) -> Brief:
    """day＝情報日報當天的紀錄；start＝本期收錄的第一天（含）。"""
    as_of = dt.date.fromisoformat(day["as_of"])
    rel = [
        r
        for r in day["records"]
        if r["relevant"] and r.get("published") and r["published"] >= start.isoformat()
    ]
    order = lambda r: (-r.get("importance", 0), -r["score"], r["published"] or "", r["id"])  # noqa: E731
    by_name = {t["name"]: t for t in catalog.topics}
    groups: dict[str, list[dict]] = {}
    unplaced = []
    for r in sorted(rel, key=order):
        name = r.get("topic") or ""
        if name in by_name:
            groups.setdefault(name, []).append(r)
        else:
            unplaced.append(r)
    kw = keyword_lines(keywords_path) if keywords_path else {}
    extras = extras or {}
    b = Brief(as_of, start, day.get("level") or "內部一般", day["run_id"], catalog)
    shown_total = 0
    for cat in catalog.categories:
        topics = []
        for t in [t for t in catalog.topics if t["category"] == cat["id"]]:
            items = groups.get(t["name"], [])
            show = items[: per_topic or None]
            b.more += len(items) - len(show)
            cards = []
            for i, r in enumerate(show, start=1):
                cards.append(
                    {
                        "code": f"{t['code']}-{i}",
                        "imp": int(r.get("importance", 0)),
                        "title": r["title"],
                        "url": r["url"],
                        "sources": "、".join(r["sources"]) or "待補",
                        "date": r["published"],
                        "terms": "、".join(r["matched_terms"]),
                        "excerpt": r.get("excerpt") or "",
                        "implication": (extras.get("implications") or {}).get(r["id"], ""),
                        "topic": t["name"],
                    }
                )
            shown_total += len(cards)
            topics.append(
                {
                    "code": t["code"],
                    "name": t["name"],
                    "keywords": kw.get(t["name"], ""),
                    "count": len(items),
                    "items": cards,
                    "view": (extras.get("views") or {}).get(t["code"], ""),
                }
            )
        b.categories.append({**cat, "topics": topics})
    b.total = shown_total
    b.empty = sum(1 for c in b.categories for t in c["topics"] if not t["items"])
    cards = [it for c in b.categories for t in c["topics"] for it in t["items"]]
    ranked = sorted(cards, key=lambda it: -it["imp"])  # 穩定排序：同分時維持主題順序
    b.key_items = [it for it in ranked if it["imp"] >= 4]
    seen: set[str] = set()
    for it in ranked:
        if it["topic"] in seen:
            continue
        seen.add(it["topic"])
        b.points.append(it)
        if len(b.points) >= catalog.key_points:
            break
    b.radar = extras.get("radar") or []
    b.schedule = extras.get("schedule") or []
    span = f"{short(start)} 至 {short(as_of)}" if start != as_of else short(as_of)
    weekend = "含週末，" if as_of.weekday() == 0 and start < as_of else ""
    if cards:
        tops = "；".join(f"〈{it['title']}〉" for it in ranked[:3])
        b.headline = (
            f"本期涵蓋 {span}，{weekend}共 {b.total} 則情資，分屬 {b.topic_count} 個主題"
            f"（其中 {b.empty} 個從缺）。重要程度最高的是：{tops}。"
        )
        clients = [it for it in cards if it["topic"] == "客戶動態"]
        if clients:
            b.headline += (
                "客戶方面：" + "；".join(f"〈{it['title']}〉" for it in clients[:2]) + "。"
            )
    else:
        b.headline = f"本期涵蓋 {span}，沒有符合關鍵字的新聞。"
    errors = [a["source"] for a in day.get("anomalies", []) if a.get("level") == "error"]
    b.notes = [
        f"蒐集範圍：以 {wd(as_of)} 為簡報日，收錄 {span} 發布的新聞{('，週末併入本期' if weekend else '')}；"
        "沒有發布日期的新聞不收。",
        f"主題分類：依副執行長 10/15 提供的關鍵字清單整併為 {b.topic_count} 個主題、四大類；"
        f"每主題列前 {per_topic or '全部'} 則，總則數不設上限。"
        + (f"本期另有 {b.more} 則同主題新聞未列出。" if b.more else ""),
        "依回饋單調整：TAISE 只當來源（須命中其他關鍵字才列入）。",
        "【】重要程度："
        + "、".join(
            f"{k} {v}" for k, v in sorted(catalog.importance.items(), reverse=True) if k >= 2
        )
        + "。",
        "「來源簡介」是新聞來源自帶的原文簡介，不是摘要；系統尚未接大模型，"
        "所以本期沒有「主題觀點」「對優樂地的意涵」「商機與行動雷達」「近期重要日程」。引用前請以原文為準。",
    ]
    if errors:
        b.notes.append(f"本期抓取失敗的來源：{'、'.join(errors)}。")
    if unplaced:
        b.notes.append(f"另有 {len(unplaced)} 則相關新聞沒有對應主題，未列出。")
    return b


# ---------------- 純文字（郵件備份、檢查用） ----------------
def render_text(b: Brief) -> str:
    c = b.catalog
    out = [
        f"資料等級：{b.level}｜{c.audience}",
        f"{c.title}　{wd(b.as_of)}",
        c.subtitle,
        "",
        "今日一句話",
        b.headline,
        "",
        "一、今日要點",
    ]
    for i, it in enumerate(b.points, 1):
        out += [f"{i}　［{it['topic']}］{it['title']}"]
        if it["excerpt"]:
            out.append(f"   {_cut(it['excerpt'], 90)}")
        out.append(f"   → 詳見 {it['code']}")
    if b.key_items:
        out += ["", f"重要程度 5、4 的新聞（{len(b.key_items)} 則）"]
        out += [f"{it['code']}　【{it['imp']}】{it['title']}" for it in b.key_items]
    out += ["", "二、主題索引"]
    for cat in b.categories:
        out.append(f"{cat['id']}、{cat['name']}")
        for t in cat["topics"]:
            cnt = f"{t['count']} 則" if t["count"] else "從缺"
            out.append(f"  {t['code']} {t['name']}　{cnt}")
    out += ["", "三、主題情資"]
    for cat in b.categories:
        out += ["", f"{cat['id']}、{cat['name']}"]
        for t in cat["topics"]:
            out.append(f"■ {t['code']} {t['name']}" + ("　本期從缺" if not t["items"] else ""))
            for it in t["items"]:
                out += [
                    f"{it['code']}　【{it['imp']}】{it['title']}",
                    f"   {it['sources']}｜{it['date']}｜命中：{it['terms']}",
                ]
                if it["excerpt"]:
                    out.append(f"   來源簡介：{_cut(it['excerpt'], 150)}")
                out += [f"   連結：{it['url']}", ""]
    out += ["", "四、說明"] + [f"・{n}" for n in b.notes]
    out += [
        "",
        "---",
        f"本期共 {b.total} 則，{b.topic_count} 個主題（其中 {b.empty} 個從缺）｜"
        f"資料截至：{b.as_of.isoformat()}｜資料等級：{b.level}｜執行編號：{b.run_id}",
        "本郵件由系統自動產生，只寄給公司內部指定同仁，請勿轉寄給客戶。",
    ]
    return "\n".join(out) + "\n"


def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------- HTML（郵件內文，內嵌樣式；也可直接列印成 A4） ----------------
def e(s: object) -> str:
    return html.escape(str(s), quote=True)


def _badge(b: Brief, imp: int) -> str:
    label = b.catalog.importance.get(imp, "")
    bars = "▮" * imp + "<span style='opacity:.25'>" + "▮" * (5 - imp) + "</span>"
    solid = imp >= 5
    style = (
        f"background:{BRAND};color:#fff;border:1px solid {BRAND};"
        if solid
        else f"background:#fff;color:{BRAND if imp >= 3 else MUTED};border:1px solid {BRAND if imp >= 3 else '#B9C2BE'};"
    )
    return (
        f"<span style='{style}border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700;"
        f"white-space:nowrap'>{imp}&nbsp;<span style='letter-spacing:-1px'>{bars}</span>&nbsp;{e(label)}</span>"
    )


def _cat_color(b: Brief, code: str) -> str:
    for cat in b.categories:
        if any(t["code"] == code.split("-")[0] for t in cat["topics"]):
            return cat["color"]
    return BRAND


def _h2(text: str) -> str:
    return f"<h2 style='font-size:21px;color:{BRAND};margin:30px 0 12px;font-weight:800'>{e(text)}</h2>"


def render_html(b: Brief) -> str:
    c = b.catalog
    font = "'Noto Sans TC','PingFang TC','Microsoft JhengHei','Helvetica Neue',Arial,sans-serif"
    p = []
    p.append(
        f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{e(c.title)} {e(b.as_of.isoformat())}</title>"
        "<style>@page{size:A4;margin:14mm 14mm 16mm}"
        "@media print{.card{break-inside:avoid}h2,h3{break-after:avoid}}</style></head>"
        f"<body style='margin:0;background:#F4F6F5;color:{INK};font-family:{font};"
        "font-size:15px;line-height:1.7'>"
        f"<div style='max-width:760px;margin:0 auto;background:{PAPER};padding:28px 26px'>"
    )
    # 刊頭
    p.append(
        f"<table width='100%' style='border-collapse:collapse;font-size:13px;color:{MUTED};"
        f"border-bottom:1px solid {LINE}'><tr><td style='padding:0 0 8px'>資料等級：{e(b.level)}｜{e(c.audience)}</td>"
        f"<td align='right' style='padding:0 0 8px'>本期共 {b.total} 則・{b.topic_count} 個主題・{b.empty} 個從缺</td></tr></table>"
        f"<div style='font-size:34px;font-weight:900;color:{BRAND};margin:14px 0 2px;letter-spacing:1px'>{e(c.title)}</div>"
        f"<table width='100%' style='border-collapse:collapse;font-size:13px;color:{MUTED}'><tr>"
        f"<td>{e(c.subtitle)}</td><td align='right' style='white-space:nowrap'>{e(wd(b.as_of))}</td></tr></table>"
    )
    p.append(
        f"<div style='background:{BRAND};color:#fff;border-radius:10px;padding:16px 18px;margin:16px 0 4px'>"
        f"<div style='font-weight:800;font-size:16px;margin-bottom:4px'>今日一句話</div>"
        f"<div style='font-size:15.5px'>{e(b.headline)}</div></div>"
    )
    # 今日要點
    if b.points:
        p.append(_h2("一、今日要點"))
        cells = []
        for i, it in enumerate(b.points, 1):
            col = _cat_color(b, it["code"])
            body = (
                f"<div style='font-size:14px;color:{INK};margin-top:6px'>{e(_cut(it['excerpt'], 90))}</div>"
                if it["excerpt"]
                else ""
            )
            cells.append(
                f"<td valign='top' width='50%' style='padding:6px'><div class='card' style='border:1px solid {LINE};"
                f"border-radius:10px;padding:14px 16px;height:100%'>"
                f"<div style='font-size:13px;font-weight:700;color:{col}'>"
                f"<span style='display:inline-block;width:20px;height:20px;line-height:20px;text-align:center;"
                f"border-radius:50%;background:{BRAND};color:#fff;font-size:12px;margin-right:6px'>{i}</span>{e(it['topic'])}</div>"
                f"<div style='font-size:16.5px;font-weight:800;margin-top:8px;line-height:1.5'>"
                f"<a href='{e(it['url'])}' style='color:{INK};text-decoration:none'>{e(it['title'])}</a></div>{body}"
                f"<div style='font-size:13px;color:{BRAND2};margin-top:8px'>→ 詳見 "
                f"<a href='#{e(it['code'])}' style='color:{BRAND2}'>{e(it['code'])}</a></div></div></td>"
            )
        rows = ["<tr>" + "".join(cells[i : i + 2]) + "</tr>" for i in range(0, len(cells), 2)]
        p.append(
            f"<table width='100%' style='border-collapse:separate;margin:0 -6px'>{''.join(rows)}</table>"
        )
    # 重要程度 5、4
    if b.key_items:
        rows = "".join(
            f"<tr><td style='padding:7px 6px;border-top:1px solid {LINE};font-weight:700;white-space:nowrap'>"
            f"<a href='#{e(it['code'])}' style='color:{INK};text-decoration:none'>{e(it['code'])}</a></td>"
            f"<td style='padding:7px 6px;border-top:1px solid {LINE};white-space:nowrap'>{_badge(b, it['imp'])}</td>"
            f"<td style='padding:7px 6px;border-top:1px solid {LINE}'><a href='{e(it['url'])}' "
            f"style='color:{INK};text-decoration:none'>{e(it['title'])}</a></td></tr>"
            for it in b.key_items
        )
        p.append(
            f"<div class='card' style='border:1px solid {LINE};border-radius:10px;padding:12px 14px;margin-top:14px'>"
            f"<div style='font-weight:800;margin-bottom:4px'>重要程度 5、4 的新聞（{len(b.key_items)} 則）</div>"
            f"<table width='100%' style='border-collapse:collapse;font-size:14px'>{rows}</table></div>"
        )
    legend = " ".join(_badge(b, k) for k in (5, 4, 3, 2))
    p.append(
        f"<div style='border:1px solid {LINE};border-radius:10px;padding:10px 14px;margin-top:12px;font-size:13px'>"
        f"<b>閱讀方式</b>　{legend}</div>"
    )
    # 研判區塊：有資料才出現
    if b.radar:
        p.append(_h2("二、商機與行動雷達"))
        p.append(_table(b.radar))
    if b.schedule:
        p.append(_h2("三、近期重要日程"))
        p.append(_table(b.schedule))
    # 主題索引
    p.append(_h2("主題索引"))
    p.append(
        f"<div style='font-size:13px;color:{MUTED};margin-bottom:6px'>則數以圓點表示；從缺主題以灰字標示，保留不刪。</div>"
    )
    rows = [
        f"<tr style='color:{BRAND};font-weight:800;font-size:14px'><td style='padding:6px;border-bottom:2px solid {BRAND}'>代碼</td>"
        f"<td style='padding:6px;border-bottom:2px solid {BRAND}'>主題</td><td style='padding:6px;border-bottom:2px solid {BRAND}'>則數</td>"
        f"<td style='padding:6px;border-bottom:2px solid {BRAND}'>本期最重要的一則</td></tr>"
    ]
    for cat in b.categories:
        rows.append(
            f"<tr><td colspan='4' style='padding:12px 6px 4px;font-weight:800;color:{cat['color']}'>{e(cat['id'])}、{e(cat['name'])}</td></tr>"
        )
        for t in cat["topics"]:
            empty = not t["items"]
            col = "#9AA39F" if empty else INK
            dots = "●" * min(t["count"], 5) if t["count"] else "從缺"
            top = t["view"] or (
                t["items"][0]["title"] if t["items"] else "本期範圍內沒有找到符合的新聞。"
            )
            rows.append(
                f"<tr style='color:{col};font-size:14px'><td style='padding:7px 6px;border-top:1px solid {LINE};"
                f"font-weight:700;color:{'#9AA39F' if empty else cat['color']}'>{e(t['code'])}</td>"
                f"<td style='padding:7px 6px;border-top:1px solid {LINE}'>{e(t['name'])}</td>"
                f"<td style='padding:7px 6px;border-top:1px solid {LINE};color:{'#9AA39F' if empty else BRAND};white-space:nowrap'>{dots}</td>"
                f"<td style='padding:7px 6px;border-top:1px solid {LINE}'>{e(top)}</td></tr>"
            )
    p.append(f"<table width='100%' style='border-collapse:collapse'>{''.join(rows)}</table>")
    # 主題情資
    p.append(_h2("主題情資"))
    for cat in b.categories:
        p.append(
            f"<h3 style='font-size:19px;color:{cat['color']};margin:26px 0 10px;padding-bottom:6px;"
            f"border-bottom:2px solid {cat['color']}'>{e(cat['id'])}、{e(cat['name'])}</h3>"
        )
        for t in cat["topics"]:
            p.append(
                f"<div style='margin:18px 0 4px'><span style='font-size:18px;font-weight:800;color:{cat['color']}'>{e(t['code'])}</span>"
                f" <span style='font-size:18px;font-weight:800'>{e(t['name'])}</span></div>"
            )
            if t["keywords"]:
                p.append(
                    f"<div style='font-size:12.5px;color:{MUTED};margin-bottom:6px'>關鍵字：{e(t['keywords'])}</div>"
                )
            if t["view"]:
                p.append(
                    f"<div style='border:1px solid {LINE};border-radius:8px;padding:8px 12px;margin:6px 0;font-size:14px'>"
                    f"<b style='color:{BRAND}'>主題觀點</b>　{e(t['view'])}</div>"
                )
            if not t["items"]:
                p.append(
                    "<div style='border:1px dashed #C8D1CD;border-radius:8px;padding:10px;text-align:center;"
                    "color:#9AA39F;font-size:13px;margin:6px 0 10px'>本期從缺</div>"
                )
            for it in t["items"]:
                strong = it["imp"] >= 5
                p.append(
                    f"<div class='card' id='{e(it['code'])}' style='border:1px solid {BRAND if strong else LINE};"
                    f"border-radius:10px;padding:14px 16px;margin:8px 0 12px'>"
                    f"<div><span style='font-weight:800;color:{cat['color']};font-size:16px'>{e(it['code'])}</span>&nbsp; {_badge(b, it['imp'])}</div>"
                    f"<div style='font-size:17px;font-weight:800;margin:8px 0 2px;line-height:1.5'>"
                    f"<a href='{e(it['url'])}' style='color:{INK};text-decoration:none'>{e(it['title'])}</a></div>"
                    f"<div style='font-size:13px;color:{MUTED}'>{e(it['sources'])}｜{e(it['date'])}｜命中：{e(it['terms'])}</div>"
                    f"<div style='font-size:12px;color:{MUTED};word-break:break-all'>原文：<a href='{e(it['url'])}' style='color:{MUTED}'>{e(it['url'].split('?utm_')[0])}</a></div>"
                )
                if it["excerpt"]:
                    p.append(
                        f"<div style='margin-top:8px;font-size:12.5px;font-weight:700;color:{INK}'>來源簡介 "
                        f"<span style='font-weight:400;color:{MUTED}'>原文</span></div>"
                        f"<div style='font-size:15px'>{e(_cut(it['excerpt'], 220))}</div>"
                    )
                if it["implication"]:
                    p.append(
                        f"<div style='background:{SOFT};border:1px dashed {BRAND2};border-radius:8px;padding:8px 12px;margin-top:8px'>"
                        f"<b>對優樂地的意涵</b> <span style='border:1px solid {BRAND2};border-radius:999px;padding:0 6px;"
                        f"font-size:12px;color:{BRAND2}'>研判</span><div style='font-size:15px'>{e(it['implication'])}</div></div>"
                    )
                p.append("</div>")
    # 說明
    p.append(_h2("說明"))
    p.append("".join(f"<div style='font-size:13.5px;margin:4px 0'>{e(n)}</div>" for n in b.notes))
    p.append(
        f"<div style='font-size:13px;color:{MUTED};margin-top:10px;border-top:1px solid {LINE};padding-top:8px'>"
        f"本期共 {b.total} 則，{b.topic_count} 個主題（其中 {b.empty} 個從缺）｜資料截至 {e(b.as_of.isoformat())}｜"
        f"資料等級：{e(b.level)}｜執行編號：{e(b.run_id)}<br>本郵件由系統自動產生，只寄給公司內部指定同仁，請勿轉寄給客戶。</div>"
    )
    p.append("</div></body></html>")
    return "".join(p)


def _table(rows: list[list[str]]) -> str:
    head = "".join(
        f"<td style='padding:6px;border-bottom:2px solid {BRAND};color:{BRAND};font-weight:800'>{e(h)}</td>"
        for h in rows[0]
    )
    body = "".join(
        "<tr>"
        + "".join(f"<td style='padding:7px 6px;border-top:1px solid {LINE}'>{e(v)}</td>" for v in r)
        + "</tr>"
        for r in rows[1:]
    )
    return f"<table width='100%' style='border-collapse:collapse;font-size:14px'><tr>{head}</tr>{body}</table>"
