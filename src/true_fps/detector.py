"""Оркестрация измерения: проверка пути, метаданные, окна и итог."""

import math
from pathlib import Path

from .exceptions import VideoPathError
from .ffprobe import Ffprobe
from .measurement import build_windows, combine_windows, measure_window
from .result import FpsResult, FpsStatus


class FpsDetector:
    """Повторно используемый детектор без зависимости от приложения-потребителя."""

    def __init__(
        self,
        ffprobe_path: str | Path | None = None,
        *,
        timeout: float = 30.0,
        consistency_threshold: float = 0.01,
    ) -> None:
        if (
            isinstance(consistency_threshold, bool)
            or not math.isfinite(consistency_threshold)
            or consistency_threshold < 0
        ):
            raise ValueError("consistency_threshold должен быть конечным неотрицательным числом")
        self._probe = Ffprobe(ffprobe_path, timeout)
        self._threshold = consistency_threshold

    @property
    def ffprobe_path(self) -> Path:
        """Абсолютный путь к выбранному исполняемому файлу."""
        return Path(self._probe.executable)

    def detect(self, video_path: str | Path) -> FpsResult:
        """Измерить частоту по временной шкале; технические ошибки возбуждают исключения."""
        if not isinstance(video_path, (str, Path)):
            raise TypeError("video_path должен быть str или Path")
        if isinstance(video_path, str) and not video_path.strip():
            raise ValueError("video_path не должен быть пустым")
        try:
            video = Path(video_path).resolve(strict=True)
            if not video.is_file():
                raise VideoPathError(f"Путь не является обычным файлом: {video}")
            with video.open("rb"):
                pass
        except (OSError, RuntimeError, ValueError) as exc:
            raise VideoPathError(f"Видео недоступно: {video_path}: {exc}") from exc
        info = self._probe.video_info(video)
        if info.duration is None:
            return FpsResult(
                None,
                FpsStatus.INSUFFICIENT_DATA,
                None,
                (),
                None,
                "Нет положительной конечной длительности контейнера",
            )
        windows = tuple(
            measure_window(start, end, self._probe.timestamps(video, start, end))
            for start, end in build_windows(info.duration, info.start_time)
        )
        return combine_windows(info.duration, windows, self._threshold)


def detect_fps(
    video_path: str | Path,
    ffprobe_path: str | Path | None = None,
    *,
    timeout: float = 30.0,
    consistency_threshold: float = 0.01,
) -> FpsResult:
    """Однократное измерение тем же алгоритмом, что и FpsDetector.detect."""
    return FpsDetector(
        ffprobe_path, timeout=timeout, consistency_threshold=consistency_threshold
    ).detect(video_path)
