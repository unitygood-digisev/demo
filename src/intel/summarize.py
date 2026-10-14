"""兩句摘要：只透過 llm_client，資料等級固定為「公開」。"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from intel.dedupe import Event
from shared.llm_client import LLMClient, LLMNotConfiguredError

LEVEL = "公開"
PURPOSE = "intel_summary"
SUMMARY_MAX = 80
MEANING_MAX = 40
TITLE_ONLY = "僅標題，內容待確認"
FAILED = "摘要產生失敗，請看原文"

# 任何像連結的東西：markdown 連結、各種 scheme、www.、裸網域
_LINK = re.compile(
    r"\]\s*\("
    r"|\b(?:https?|ftps?|javascript|vbscript|mailto|data|file|tel|sms|wss?):"
    r"|\bwww\."
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|gov|edu|tw|io|co|info|biz|me|cn|jp|uk|eu|ai|app|dev|xyz|top|site)\b",
    re.I,
)
LINK_FLAG = "模型回應含連結，已整則捨棄，請看原文"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_SENT_END = re.compile(r"[。！？!?]|\.(?=\s|$)")


@dataclass
class Summary:
    summary: str
    meaning: str
    status: str  # ok／title_only／failed
    flags: list[str] = field(default_factory=list)
    mock: bool = False

    def as_dict(self) -> dict:
        return {
            "summary": self.summary,
            "meaning": self.meaning,
            "status": self.status,
            "flags": self.flags,
            "mock": self.mock,
        }


def load_prompt(path: Path) -> tuple[str, str]:
    """回傳 (版本, 提示詞全文)。檔頭第一行必須是「版本: xxx」。"""
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text else ""
    if not first.startswith("版本:"):
        raise ValueError(f"提示詞 {path.name} 第一行必須是「版本: …」")
    return first.split(":", 1)[1].strip(), text


def build_input(event: Event) -> str:
    m = event.main
    return f"標題：{m.title}\n內文：{m.excerpt or ''}"


def intel_mock_responder(prompt: str, input_text: str) -> str:
    """模擬模型：只取文章第一句，不產生任何新內容。"""
    body = input_text.split("內文：", 1)[1] if "內文：" in input_text else ""
    first = _SENT_END.split(body.strip(), maxsplit=1)[0].strip()[:60]
    return json.dumps(
        {"摘要": f"（模擬摘要）{first}。", "意義": "（模擬）待正式模型產生"}, ensure_ascii=False
    )


_WS = re.compile(r"\s+")


def has_link(text: str) -> bool:
    return bool(_LINK.search(unicodedata.normalize("NFKC", text)))


def _chars(s: str) -> int:
    return len(re.sub(r"\s", "", s))


def parse_response(text: str) -> Summary:
    raw = _FENCE.sub("", text.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Summary(FAILED, "待補", "failed", ["模型回應格式錯誤"])
    if not isinstance(data, dict):
        return Summary(FAILED, "待補", "failed", ["模型回應格式錯誤"])
    summary, meaning = data.get("摘要"), data.get("意義")
    if not isinstance(summary, str) or not isinstance(meaning, str) or not summary.strip():
        return Summary(FAILED, "待補", "failed", ["模型回應缺少摘要或意義"])
    # 連結一律只來自輸入 RSS：模型回應裡出現任何像連結的東西，整則捨棄
    if has_link(summary) or has_link(meaning):
        return Summary(FAILED, "待補", "failed", [LINK_FLAG])
    # 換行與多餘空白壓成一個空白，避免插入假段落
    summary, meaning = _WS.sub(" ", summary).strip(), _WS.sub(" ", meaning).strip()
    if not summary:
        return Summary(FAILED, "待補", "failed", ["模型回應缺少摘要或意義"])
    flags: list[str] = []
    if _chars(summary) > SUMMARY_MAX:
        flags.append(f"摘要超過 {SUMMARY_MAX} 字，待人工確認")
    if len([s for s in _SENT_END.split(summary) if s.strip()]) > 2:
        flags.append("摘要超過兩句，待人工確認")
    if _chars(meaning) > MEANING_MAX:
        flags.append(f"意義超過 {MEANING_MAX} 字，待人工確認")
    return Summary(summary.strip(), meaning.strip() or "待補", "ok", flags)


class Summarizer:
    def __init__(self, client: LLMClient, prompt_path: Path, backend: str | None = None) -> None:
        self.client = client
        self.version, self.prompt = load_prompt(prompt_path)
        self.backend = backend or client.default_backend
        self.mock = client.backends.get(self.backend, {}).get("processing") == "mock"

    def summarize(self, event: Event, run_id: str | None = None) -> Summary:
        if not (event.main.excerpt or "").strip():
            return Summary(TITLE_ONLY, "待補", "title_only")
        try:
            res = self.client.complete(
                level=LEVEL,
                purpose=PURPOSE,
                prompt_version=self.version,
                prompt=self.prompt,
                input_text=build_input(event),
                backend=self.backend,
                run_id=run_id,
            )
        except LLMNotConfiguredError:
            return Summary(FAILED, "待補", "failed", ["正式模型尚未設定"], self.mock)
        s = parse_response(res.text)
        s.mock = self.mock
        return s
