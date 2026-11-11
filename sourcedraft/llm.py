"""Claude client for the two model calls in the pipeline (Step 1 extract, Step 2 draft)."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

DEFAULT_MODEL = os.environ.get("SOURCEDRAFT_MODEL", "claude-opus-5-5")
DEFAULT_EFFORT = os.environ.get("SOURCEDRAFT_EFFORT", "high")


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def extract(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...

    def draft(self, system: str, user: str) -> str: ...


class ClaudeLLM:
    """Streams every request (long inputs/outputs) and lets the server fall back on a refusal."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, max_tokens: int = 64000):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.usage: list[dict[str, Any]] = []

    def _run(self, system: str, user: str, output_config: dict[str, Any]) -> str:
        anthropic = self._anthropic
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config=output_config,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMError("Claude API 認證失敗：請設定 ANTHROPIC_API_KEY") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Claude API 流量限制，請稍後重試") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API 錯誤（{exc.status_code}）：{exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("無法連線至 Claude API，請檢查網路") from exc
        except TypeError as exc:  # raised by the SDK when no credential can be resolved
            if "authentication" in str(exc):
                raise LLMError("找不到 Claude API 憑證：請設定 ANTHROPIC_API_KEY 或執行 ant auth login") from exc
            raise

        self.usage.append({"model": message.model, "input_tokens": message.usage.input_tokens,
                           "output_tokens": message.usage.output_tokens})
        if message.stop_reason == "refusal":
            raise LLMError("模型拒絕處理此請求（refusal），請檢查輸入物料內容")
        if message.stop_reason == "max_tokens":
            raise LLMError("輸出超過長度上限而被截斷，請將章節拆小後重跑")
        text = "".join(b.text for b in message.content if b.type == "text")
        if not text.strip():
            raise LLMError("模型未回傳任何文字")
        return text

    def extract(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        text = self._run(system, user, {"effort": self.effort,
                                        "format": {"type": "json_schema", "schema": schema}})
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Step 1 回傳的 JSON 無法解析") from exc

    def draft(self, system: str, user: str) -> str:
        return self._run(system, user, {"effort": self.effort})
