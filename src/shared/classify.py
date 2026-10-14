"""資料分級：讀 config/classification.yaml，判斷某等級允許哪些處理。"""

from __future__ import annotations

from pathlib import Path

from shared.config import load_yaml


class ClassificationError(PermissionError):
    """資料等級不允許這種處理。"""


class Classifier:
    def __init__(self, config_dir: Path | None = None) -> None:
        cfg = load_yaml("classification.yaml", config_dir)
        self.levels: dict[str, dict] = cfg["levels"]
        self.default_level: str = cfg.get("default_level", "客戶機密")
        self.casebase_allowed: list[str] = cfg.get("casebase_allowed", [])
        if self.default_level not in self.levels:
            raise ValueError(f"default_level「{self.default_level}」不在分級清單中")

    def normalize(self, level: str | None) -> str:
        """不認得或沒給的等級，一律當作最嚴格的預設等級（客戶機密）。"""
        if level in self.levels:
            return level  # type: ignore[return-value]
        return self.default_level

    def is_known(self, level: str | None) -> bool:
        return level in self.levels

    def rank(self, level: str | None) -> int:
        return int(self.levels[self.normalize(level)]["rank"])

    def allowed_processing(self, level: str | None) -> list[str]:
        return list(self.levels[self.normalize(level)].get("allowed_processing", []))

    def allows(self, level: str | None, processing: str) -> bool:
        return processing in self.allowed_processing(level)

    def require(self, level: str | None, processing: str) -> None:
        """不允許就丟例外。"""
        if not self.allows(level, processing):
            raise ClassificationError(
                f"資料等級「{self.normalize(level)}」不允許處理方式「{processing}」"
            )

    def highest(self, levels: list[str | None]) -> str:
        """多份資料合併時，取最高（最嚴格）的等級。空清單視為預設等級。"""
        if not levels:
            return self.default_level
        return max((self.normalize(lv) for lv in levels), key=self.rank)
