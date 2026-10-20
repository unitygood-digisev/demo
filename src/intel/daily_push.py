"""每日情報郵件（階段 1b）：跑一次外部情報日報，整理成手機看得完的郵件，寄給白名單同仁。

郵件只有公開新聞的標題、來源、日期、命中的關鍵字與連結，不放任何內部資料。
同一天重跑不會重寄（由 shared.mail_client 控管）。郵件內容另存一份文字檔在本機。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from intel import brief as briefmod
from intel.pipeline import RunConfig, default_keywords_path
from intel.pipeline import run as run_intel
from shared.classify import Classifier
from shared.config import PROJECT_ROOT, load_yaml, threshold
from shared.dates import today_tw
from shared.mail_client import MailClient, MailError, MailNotConfigured

LEVEL = "內部一般"  # 新聞本身公開，但「命中關鍵字」會顯示客戶名稱；關鍵字檔標得更高時取高者
KIND = "intel_daily"


@dataclass
class PushConfig:
    as_of: dt.date
    sources_path: Path = PROJECT_ROOT / "config" / "sources.yaml"
    keywords_path: Path = field(default_factory=default_keywords_path)
    interim_dir: Path = PROJECT_ROOT / "data" / "interim" / "intel"
    out_dir: Path = PROJECT_ROOT / "data" / "out" / "intel"
    config_dir: Path | None = None
    offline: bool = False
    log_dir: Path | None = None
    mail: MailClient | None = None
    send: bool = True
    today: dt.date | None = None  # 測試用；預設台灣今天。只有今天的日報可以寄
    # 以下為「版本」設定（config/push_profiles.yaml）；預設值＝主管版，行為與原本相同
    brief_name: str = "brief.yaml"
    kind: str = KIND
    draft_prefix: str = "郵件_情資日報"
    recipients_env: str | None = None  # 只有指定版本時才換收件人變數，避免寄到主管版收件人
    per_topic: int | None = None  # None＝用 thresholds.yaml 的 daily_mail_per_topic


class ProfileError(MailError):
    """版本設定有問題時丟出，不產生草稿、不寄信。"""


def apply_profile(cfg: PushConfig, name: str, config_dir: Path | None = None) -> str:
    """依 config/push_profiles.yaml 套用指定版本，回傳版本名稱。設定不完整就報錯。"""
    cdir = config_dir or PROJECT_ROOT / "config"
    try:
        profiles = load_yaml("push_profiles.yaml", config_dir).get("profiles") or {}
    except FileNotFoundError as e:
        raise ProfileError("找不到 config/push_profiles.yaml，無法使用 --profile") from e
    p = profiles.get(name)
    if not isinstance(p, dict):
        raise ProfileError(
            f"config/push_profiles.yaml 沒有「{name}」這個版本（目前有：{'、'.join(profiles) or '無'}）"
        )
    need = ("名稱", "關鍵字", "版面", "資料夾", "收件人環境變數", "郵件種類")
    missing = [k for k in need if not str(p.get(k) or "").strip()]
    if missing:
        raise ProfileError(f"版本「{name}」缺少欄位：{'、'.join(missing)}")
    kw = cdir / str(p["關鍵字"])
    local = kw.with_name(kw.stem + ".local.yaml")
    cfg.keywords_path = local if local.is_file() else kw
    if not cfg.keywords_path.is_file():
        raise ProfileError(f"找不到版本「{name}」的關鍵字檔 {kw.name}")
    if not (cdir / str(p["版面"])).is_file():
        raise ProfileError(f"找不到版本「{name}」的版面檔 {p['版面']}")
    cfg.brief_name = str(p["版面"])
    folder = str(p["資料夾"])
    cfg.interim_dir = PROJECT_ROOT / "data" / "interim" / folder
    cfg.out_dir = PROJECT_ROOT / "data" / "out" / folder
    cfg.kind = str(p["郵件種類"])
    cfg.recipients_env = str(p["收件人環境變數"])
    cfg.draft_prefix = f"郵件_情資日報_{p['名稱']}"
    n = p.get("每主題則數")
    if n is not None:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ProfileError(f"版本「{name}」的每主題則數應為 1 以上的整數（目前是「{n}」）")
        cfg.per_topic = n
    return str(p["名稱"])


@dataclass
class PushResult:
    draft: Path
    sent: bool
    message: str


def _int_threshold(key: str, minimum: int, config_dir: Path | None, allow_none: bool = False):
    v = threshold("intel", key, config_dir)[0]
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise MailError(
            f"config/thresholds.yaml 的 intel.{key} 應為 {minimum} 以上的整數（目前是「{v}」）"
        )
    return v


def window_start(as_of: dt.date, lookback_days: int) -> dt.date:
    """只列這一天（含）之後發布的新聞。週一往前多算週六、週日。"""
    extra = 2 if as_of.weekday() == 0 else 0
    return as_of - dt.timedelta(days=lookback_days + extra)


def mail_level(day: dict) -> str:
    return Classifier().highest([LEVEL, day.get("level") or LEVEL])


def compose(
    day: dict,
    per_topic: int | None = 3,
    lookback_days: int | None = None,
    max_items: int | None = None,
) -> tuple[str, str]:
    """回傳 (主旨, 內文)。第一句講結論。

    依主題分組（副執行長 2026-10-19 回饋）：每個主題列重要程度最高的前 per_topic 則；
    主題依其中最高的重要程度排序。max_items 是總則數上限，None＝不設上限。
    lookback_days：只列最近幾天發布的新聞。雲端排程每天是全新環境、記不得昨天寄過什麼，
    用發布日期避免同一則新聞連續幾天出現。沒有發布日期的不列入，並註明則數。
    """
    rel = [r for r in day["records"] if r["relevant"]]
    old = undated = 0
    if lookback_days is not None:
        start = window_start(dt.date.fromisoformat(day["as_of"]), lookback_days).isoformat()
        undated = sum(1 for r in rel if not r["published"])
        old = sum(1 for r in rel if r["published"] and r["published"] < start)
        rel = [r for r in rel if r["published"] and r["published"] >= start]
    order = lambda r: (-r.get("importance", 0), -r["score"], r["published"] or "", r["id"])  # noqa: E731
    groups: dict[str, list[dict]] = {}
    for r in sorted(rel, key=order):
        groups.setdefault(r.get("topic") or "其他", []).append(r)
    topics = sorted(groups, key=lambda t: (order(groups[t][0]), t))
    shown: list[tuple[str, list[dict]]] = []
    count = 0
    for t in topics:
        take = groups[t][: per_topic or None]
        if max_items is not None:
            take = take[: max(0, max_items - count)]
        if take:
            shown.append((t, take))
            count += len(take)
    n5 = sum(1 for r in rel if r.get("importance", 0) >= 5)
    if rel:
        first = (
            f"今天有 {len(rel)} 則相關新聞，分成 {len(groups)} 個主題，"
            f"其中重要程度 5 的有 {n5} 則。"
        )
    else:
        first = "今天沒有符合關鍵字的新聞。"
    lines = [first, ""]
    i = 0
    for t, rs in shown:
        more = len(groups[t]) - len(rs)
        lines.append(f"■ {t}（{len(groups[t])} 則" + (f"，列出前 {len(rs)} 則）" if more else "）"))
        for r in rs:
            i += 1
            src = "、".join(r["sources"]) or "待補"
            terms = "、".join(r["matched_terms"]) or "待補"
            lines += [
                f"{i}. 【重要程度 {r.get('importance', 0)}】{r['title']}",
                f"   來源：{src}｜日期：{r['published'] or '待補'}｜關鍵字：{terms}",
            ]
            if r.get("excerpt"):
                ex = r["excerpt"] if len(r["excerpt"]) <= 150 else r["excerpt"][:149] + "…"
                lines.append(f"   來源簡介：{ex}")
            lines += [f"   連結：{r['url']}", ""]
    if len(rel) > count:
        lines += [f"（另有 {len(rel) - count} 則同主題的新聞未列出，見本機的情報日報檔）", ""]
    if old or undated:
        parts = ([f"{old} 則較早發布"] if old else []) + (
            [f"{undated} 則沒有發布日期"] if undated else []
        )
        lines += [f"（另有 {'、'.join(parts)}的相關新聞未列入，見本機的情報日報檔）", ""]
    errors = [a for a in day["anomalies"] if a["level"] == "error"]
    if errors:
        lines.append(
            f"注意：有 {len(errors)} 個來源今天抓取失敗：" + "、".join(a["source"] for a in errors)
        )
    if day["config_problems"]:
        lines.append(f"注意：設定有 {len(day['config_problems'])} 個問題，請負責人查看執行日誌。")
    lines += [
        "",
        "---",
        f"資料截至：{day['as_of']}｜資料等級：{mail_level(day)}｜執行編號：{day['run_id']}",
        "本郵件由系統自動產生，只寄給公司內部指定同仁，請勿轉寄給客戶。",
    ]
    subject = f"【優樂地】永續情報日報 {day['as_of']}（{len(rel)} 則）"
    return subject, "\n".join(lines) + "\n"


def run(cfg: PushConfig) -> PushResult:
    _int_threshold(
        "daily_mail_max_items", 1, cfg.config_dir, allow_none=True
    )  # 新版面不設總則數上限，只檢查設定
    per_topic = cfg.per_topic or _int_threshold(
        "daily_mail_per_topic", 1, cfg.config_dir, allow_none=True
    )
    lookback = _int_threshold("daily_mail_lookback_days", 0, cfg.config_dir)
    res = run_intel(
        RunConfig(
            as_of=cfg.as_of,
            sources_path=cfg.sources_path,
            keywords_path=cfg.keywords_path,
            interim_dir=cfg.interim_dir,
            out_dir=cfg.out_dir,
            config_dir=cfg.config_dir,
            offline=cfg.offline,
            log_dir=cfg.log_dir,
        )
    )
    level = mail_level(res.day)
    # 版面依副執行長修訂版（永續情資日報）：依 16 個主題分組、每主題前 per_topic 則
    catalog = briefmod.Catalog.load(cfg.config_dir, cfg.brief_name)
    start = window_start(cfg.as_of, lookback)
    b = briefmod.build(res.day, catalog, start, per_topic, cfg.keywords_path)
    b.level = level
    subject = f"【優樂地】{catalog.title} {cfg.as_of.isoformat()}（{b.total} 則）"
    body, html_body = briefmod.render_text(b), briefmod.render_html(b)
    stem = f"{cfg.draft_prefix}_{cfg.as_of.strftime('%Y%m%d')}"
    draft = cfg.out_dir / f"{stem}.txt"
    html_draft = cfg.out_dir / f"{stem}.html"
    mail = cfg.mail or MailClient(config_dir=cfg.config_dir)
    if cfg.recipients_env:
        mail.cfg["recipients_env"] = cfg.recipients_env
    can_send = cfg.send and cfg.as_of == (cfg.today or today_tw())
    if draft.is_file() and mail.already_sent(cfg.kind, cfg.as_of):
        # 已經寄過：保留寄出的那份草稿，不覆蓋（只產生草稿時也一樣）
        return PushResult(draft, False, "今天已經寄過，沒有重寄，寄出的草稿保留不動")
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(f"主旨：{subject}\n\n{body}", encoding="utf-8")
    html_draft.write_text(html_body, encoding="utf-8")
    if any("來源清單是空的" in p for p in res.day["config_problems"]):
        return PushResult(draft, False, "未寄出：來源清單是空的，請先設定 config/sources.yaml")
    if not cfg.send:
        return PushResult(draft, False, "未寄出：本次只產生郵件草稿")
    if not can_send:
        return PushResult(draft, False, "未寄出：只能寄今天的日報（指定了其他日期時只產生草稿）")
    try:
        sent = mail.send(subject, body, level=level, kind=cfg.kind, day=cfg.as_of, html=html_body)
    except MailNotConfigured as e:
        return PushResult(draft, False, f"未寄出：{e}")
    if not sent:
        return PushResult(draft, False, "今天已經寄過，沒有重寄")
    return PushResult(draft, True, "已寄出")
