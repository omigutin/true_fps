"""Поиск ffprobe, ограниченный по времени запуск и разбор JSON-ответов."""

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .exceptions import FfprobeNotFoundError, FfprobeTimeoutError, VideoReadError
from .measurement import validate_positive


def _number(value: object) -> float | None:
    """Разобрать только конечное число, не принимая bool за число."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """Длительность контейнера и начало его временной шкалы."""

    duration: float | None
    start_time: float


class Ffprobe:
    """Адаптер внешнего процесса; импорт модуля ничего не запускает."""

    def __init__(self, executable: str | Path | None = None, timeout: float = 30.0) -> None:
        validate_positive(timeout, "timeout")
        if executable is not None and not isinstance(executable, (str, Path)):
            raise TypeError("ffprobe_path должен быть str, Path или None")
        if executable is not None and not str(executable).strip():
            raise ValueError("ffprobe_path не должен быть пустым")
        command = "ffprobe" if executable is None else str(executable)
        # Path означает путь, даже если имя не содержит разделителя.
        if isinstance(executable, Path):
            command = str(executable.resolve())
        found = shutil.which(command)
        if found is None:
            raise FfprobeNotFoundError(f"ffprobe не найден или не исполняемый: {command}")
        self.executable = str(Path(found).resolve())
        self.timeout = timeout

    def _run(self, arguments: list[str], video: Path) -> dict[str, object]:
        """Запустить без оболочки; техническая ошибка никогда не становится результатом."""
        command = [self.executable, "-v", "error", *arguments, "-of", "json", str(video)]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise FfprobeTimeoutError(
                f"ffprobe превысил таймаут {self.timeout} с для '{video}'"
            ) from exc
        except OSError as exc:
            raise FfprobeNotFoundError(f"Не удалось запустить ffprobe: {exc}") from exc
        except subprocess.SubprocessError as exc:
            raise VideoReadError(f"Сбой процесса ffprobe для '{video}': {exc}") from exc
        if completed.returncode != 0 or completed.stderr.strip():
            raise VideoReadError(
                f"ffprobe не прочитал '{video}' (код {completed.returncode}): "
                f"{completed.stderr.strip()[:2000]}"
            )
        try:
            data: object = json.loads(completed.stdout)
        except (ValueError, RecursionError) as exc:
            raise VideoReadError("ffprobe вернул некорректный JSON") from exc
        if not isinstance(data, dict):
            raise VideoReadError("Ответ ffprobe должен быть JSON-объектом")
        return cast(dict[str, object], data)

    def video_info(self, video: Path) -> VideoInfo:
        """Прочитать длительность и проверить наличие первого видеопотока."""
        data = self._run(
            ["-select_streams", "v:0", "-show_entries", "format=duration,start_time:stream=index"],
            video,
        )
        streams = data.get("streams")
        if not isinstance(streams, list):
            raise VideoReadError("В ответе ffprobe отсутствует список видеопотоков")
        if not streams:
            raise VideoReadError("В файле отсутствует видеопоток v:0")
        metadata = data.get("format")
        if not isinstance(metadata, dict):
            raise VideoReadError("В ответе ffprobe отсутствует объект format")
        duration = _number(metadata.get("duration"))
        start = _number(metadata.get("start_time"))
        return VideoInfo(duration if duration is not None and duration > 0 else None, start or 0.0)

    def timestamps(self, video: Path, start: float, end: float) -> tuple[float | None, ...]:
        """Прочитать реальные метки до абсолютного конца окна, включая ранний seek."""
        data = self._run(
            [
                "-select_streams",
                "v:0",
                "-read_intervals",
                f"{start:.9f}%{end:.9f}",
                "-show_entries",
                "frame=best_effort_timestamp_time",
            ],
            video,
        )
        frames = data.get("frames")
        if not isinstance(frames, list):
            raise VideoReadError("В ответе ffprobe отсутствует список frames")
        result: list[float | None] = []
        for frame in frames:
            if not isinstance(frame, dict):
                raise VideoReadError("В ответе ffprobe кадр не является объектом")
            result.append(_number(frame.get("best_effort_timestamp_time")))
        return tuple(result)
