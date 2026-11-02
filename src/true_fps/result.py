"""Неизменяемые результаты измерений и отдельная оценка согласованности."""

from dataclasses import dataclass
from enum import Enum


class FpsStatus(str, Enum):
    """Согласованность выборочных окон, а не гарантия частоты съёмки."""

    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class WindowMeasurement:
    """Запрошенное окно и фактические границы пригодных временных меток."""

    start_seconds: float
    end_seconds: float
    sample_count: int
    invalid_count: int
    first_timestamp: float | None
    last_timestamp: float | None
    fps: float | None
    reason: str | None = None

    @property
    def interval_count(self) -> int:
        """Число интервалов пригодного окна; для отклонённого окна — ноль."""
        return self.sample_count - 1 if self.fps is not None else 0

    @property
    def elapsed_seconds(self) -> float:
        """Фактическая длительность пригодного окна по меткам."""
        if self.fps is None or self.first_timestamp is None or self.last_timestamp is None:
            return 0.0
        return self.last_timestamp - self.first_timestamp


@dataclass(frozen=True, slots=True)
class FpsResult:
    """FPS сохраняется и при расхождении окон; отсутствие значения обозначается None."""

    fps: float | None
    status: FpsStatus
    duration_seconds: float | None
    windows: tuple[WindowMeasurement, ...]
    relative_spread: float | None
    reason: str

    @property
    def usable_window_count(self) -> int:
        """Число пригодных окон, участвовавших в вычислении."""
        return sum(window.fps is not None for window in self.windows)

    @property
    def is_consistent(self) -> bool:
        """Подтверждена ли согласованность хотя бы двух окон."""
        return self.status is FpsStatus.CONSISTENT
