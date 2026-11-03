""" Чистые вычисления: окна, измерения и взвешенная оценка согласованности. """

import math
import statistics
from collections.abc import Sequence

from .result import FpsResult, FpsStatus, WindowMeasurement


def validate_positive(value: float, name: str) -> None:
    """ Проверить положительный конечный параметр, исключая bool. """
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


def build_windows(duration: float, origin: float = 0.0) -> tuple[tuple[float, float], ...]:
    """ Окна около 10%, 50% и 90%, не длиннее 5 секунд и duration / 6. """
    validate_positive(duration, "duration")
    if not math.isfinite(origin):
        raise ValueError("origin must be a finite number")
    length = min(5.0, duration / 6.0)
    if length == 0.0:
        return ()
    windows: list[tuple[float, float]] = []
    for fraction in (0.1, 0.5, 0.9):
        start = min(max(duration * fraction - length / 2.0, 0.0), duration - length)
        left, right = origin + start, origin + start + length
        if right > left and (not windows or left >= windows[-1][1]):
            windows.append((left, right))
    return tuple(windows)


def measure_window(
    start: float, end: float, timestamps: Sequence[float | None]
) -> WindowMeasurement:
    """
    Отклонить пропуски, дубликаты и немонотонные метки, не скрывая их сортировкой.

    Метки вне запрошенного окна отбрасываются: seek ffprobe может начаться раньше.
    Отсутствующая или неконечная метка между первой и последней меткой окна (в порядке
    выдачи) делает окно непригодным, поскольку её удаление занизило бы число кадров
    в формуле. Такие метки до первой и после последней метки окна на число интервалов
    не влияют и окно не портят: ffprobe отдаёт их, например, при досбросе декодера
    в конце чтения. Все они учитываются в invalid_count.
    """
    invalid = sum(1 for value in timestamps if not _is_valid(value))
    inside = [
        (index, value)
        for index, value in enumerate(timestamps)
        if value is not None and math.isfinite(value) and start <= value <= end
    ]
    values = [value for _, value in inside]
    reason: str | None = None
    fps: float | None = None
    first, last = (values[0], values[-1]) if values else (None, None)
    gap = bool(inside) and not all(
        _is_valid(value) for value in timestamps[inside[0][0] : inside[-1][0] + 1]
    )
    if gap:
        reason = "Есть отсутствующие, нечисловые или неконечные временные метки внутри окна"
    elif len(values) < 2:
        reason = "В запрошенном окне меньше двух временных меток"
    elif any(right <= left for left, right in zip(values, values[1:], strict=False)):
        reason = "Метки повторяются или не возрастают строго"
    else:
        elapsed = values[-1] - values[0]
        value = (len(values) - 1) / elapsed
        if math.isfinite(elapsed) and math.isfinite(value) and value > 0:
            fps = value
        else:
            reason = "Численно непригодный интервал временных меток"
    return WindowMeasurement(start, end, len(values), invalid, first, last, fps, reason)


def _is_valid(value: float | None) -> bool:
    """ Метка пригодна для расчёта: есть и конечна. """
    return value is not None and math.isfinite(value)


def combine_windows(
    duration: float | None,
    windows: Sequence[WindowMeasurement],
    threshold: float,
) -> FpsResult:
    """ Объединить интервалы, сохранив значение отдельно от статуса согласованности. """
    if isinstance(threshold, bool) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be a finite non-negative number")
    usable = [window for window in windows if window.fps is not None]
    result_windows = tuple(windows)
    if not usable:
        return FpsResult(
            None,
            FpsStatus.INSUFFICIENT_DATA,
            duration,
            result_windows,
            None,
            "Нет пригодных окон с двумя строго возрастающими временными метками",
        )
    elapsed = math.fsum(window.elapsed_seconds for window in usable)
    fps = sum(window.interval_count for window in usable) / elapsed
    if not math.isfinite(fps) or fps <= 0:
        return FpsResult(
            None,
            FpsStatus.INSUFFICIENT_DATA,
            duration,
            result_windows,
            None,
            "Взвешенное значение FPS не является положительным конечным числом",
        )
    if len(usable) == 1:
        return FpsResult(
            fps,
            FpsStatus.INSUFFICIENT_DATA,
            duration,
            result_windows,
            None,
            "Пригодно только одно окно: FPS вычислен, согласованность проверить нельзя",
        )
    rates = [window.fps for window in usable if window.fps is not None]
    spread = (max(rates) - min(rates)) / statistics.median(rates)
    consistent = spread <= threshold
    reason = (
        f"Согласованы {len(usable)} из {len(windows)} окон"
        if consistent
        else f"Относительный разброс {spread:.6g} превышает порог {threshold:.6g}; "
        "это не доказывает повреждение видео"
    )
    return FpsResult(
        fps,
        FpsStatus.CONSISTENT if consistent else FpsStatus.INCONSISTENT,
        duration,
        result_windows,
        spread,
        reason,
    )
