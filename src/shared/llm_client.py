"""唯一的大模型入口（CLAUDE.md 第 4 節）。

任何程式要用大模型，都只能透過這裡的 LLMClient.complete()。它會：
1. 檢查資料等級：沒給、不認得的等級一律拒絕；超過用途上限也拒絕。
2. 檢查後端：該等級不允許的處理方式（例如內部敏感送雲端）一律拒絕。
3. 溫度固定 0，相同輸入使用快取。
4. 每次呼叫（含被拒絕的）寫一行到 logs/model_calls.jsonl，只記雜湊不記全文。

階段 0 只實作 mock 後端，不連任何真實模型服務，也不 import 任何大模型 SDK。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shared.classify import Classifier
from shared.config import PROJECT_ROOT, load_yaml
from shared.dates import now_tw


class LLMPolicyError(PermissionError):
    """違反資料分級或用途規則，呼叫被拒絕。"""


class LLMNotConfiguredError(RuntimeError):
    """後端尚未設定或尚未實作。"""


@dataclass(frozen=True)
class LLMResult:
    text: str
    cached: bool
    backend: str
    model: str
    input_hash: str


MockResponder = Callable[[str, str], str]


def _default_mock(prompt: str, input_text: str) -> str:
    # 不回傳輸入原文，避免快取檔留下明文
    return f"（模擬回應）{_sha256(input_text)[:8]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(
        self,
        config_dir: Path | None = None,
        cache_dir: Path | None = None,
        log_path: Path | None = None,
        mock_responder: MockResponder | None = None,
    ) -> None:
        cfg = load_yaml("llm.yaml", config_dir)
        self.classifier = Classifier(config_dir)
        self.temperature = cfg.get("temperature", 0)
        if self.temperature != 0:
            raise ValueError("llm.yaml 的 temperature 必須是 0")
        self.default_backend: str = cfg.get("default_backend", "mock")
        self.backends: dict[str, dict] = cfg.get("backends", {})
        self.purposes: dict[str, dict] = cfg.get("purposes", {})
        self.mock_all_levels: bool = bool(cfg.get("mock_allowed_for_all_levels", False))
        self.cache_dir = cache_dir or PROJECT_ROOT / cfg.get("cache_dir", "data/interim/llm_cache")
        self.log_path = log_path or PROJECT_ROOT / cfg.get("call_log", "logs/model_calls.jsonl")
        self.mock_responder = mock_responder or _default_mock

    # ---- 規則檢查 ----
    def check(self, level: str | None, purpose: str, backend: str) -> None:
        """不符合規則就丟 LLMPolicyError。"""
        if not level or not isinstance(level, str):
            raise LLMPolicyError("呼叫大模型必須指定資料等級（文字）")
        if not self.classifier.is_known(level):
            raise LLMPolicyError(f"不認得的資料等級「{level}」，視同客戶機密，拒絕呼叫")
        if purpose not in self.purposes:
            raise LLMPolicyError(f"用途「{purpose}」未在 llm.yaml 登記，拒絕呼叫")
        max_level = self.purposes[purpose]["max_level"]
        if self.classifier.rank(level) > self.classifier.rank(max_level):
            raise LLMPolicyError(
                f"用途「{purpose}」最高只能處理「{max_level}」資料，收到「{level}」，拒絕呼叫"
            )
        if backend not in self.backends:
            raise LLMPolicyError(f"後端「{backend}」未在 llm.yaml 登記")
        processing = self.backends[backend]["processing"]
        if processing == "mock" and self.mock_all_levels:
            return
        if not self.classifier.allows(level, processing):
            raise LLMPolicyError(
                f"資料等級「{level}」不允許使用後端「{backend}」（{processing}），拒絕呼叫"
            )

    # ---- 呼叫 ----
    def complete(
        self,
        *,
        level: str | None,
        purpose: str,
        prompt_version: str,
        prompt: str,
        input_text: str,
        backend: str | None = None,
        run_id: str | None = None,
    ) -> LLMResult:
        backend = backend or self.default_backend
        model = str(self.backends.get(backend, {}).get("model"))
        input_hash = _sha256(input_text)
        base = {
            "level": level if isinstance(level, str) or level is None else repr(level),
            "purpose": purpose,
            "prompt_version": prompt_version,
            "backend": backend,
            "model": model,
            "input_hash": input_hash,
            "run_id": run_id,
        }
        try:
            self.check(level, purpose, backend)
        except LLMPolicyError as e:
            self._log({**base, "status": "rejected", "reason": str(e), "cached": False})
            raise

        cache_key = _sha256(
            json.dumps(
                [backend, model, purpose, prompt_version, self.temperature, prompt, input_text],
                ensure_ascii=False,
            )
        )
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            text = json.loads(cache_file.read_text(encoding="utf-8"))["text"]
            self._log({**base, "status": "ok", "cached": True})
            return LLMResult(text, True, backend, model, input_hash)

        try:
            text = self._call_backend(backend, prompt, input_text)
        except Exception as e:
            self._log({**base, "status": "error", "reason": str(e), "cached": False})
            raise
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
        self._log({**base, "status": "ok", "cached": False})
        return LLMResult(text, False, backend, model, input_hash)

    def _call_backend(self, backend: str, prompt: str, input_text: str) -> str:
        processing = self.backends[backend]["processing"]
        if processing == "mock":
            return self.mock_responder(prompt, input_text)
        raise LLMNotConfiguredError(
            f"後端「{backend}」尚未實作；階段 0 只提供 mock。接真實服務前需主管同意。"
        )

    def _log(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"time": now_tw().isoformat(timespec="seconds"), **record}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
