""" Поиск ffprobe, ограниченный по времени запуск и разбор JSON-ответов. """

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .exceptions import FfprobeNotFoundError, FfprobeTimeoutError, VideoReadError
from .measurement import validate_positive

# Сколько символов stderr ffprobe сохранять в сообщениях и предупреждениях.
_STDERR_LIMIT = 2000


def _number(value: object) -> float | None:
    """ Разобрать только конечное число, не принимая bool за число. """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    """ Положительное конечное число или None. """
    number = _number(value)
    return number if number is not None and number > 0 else None


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """ Длительность видеопотока и начало его временной шкалы. """

    duration: float | None
    start_time: float
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class FrameTimestamps:
    """ Метки кадров окна и предупреждение ffprobe, если оно было. """

    values: tuple[float | None, ...]
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class _Response:
    """ Разобранный JSON-ответ и текст stderr при успешном коде возврата. """

    data: dict[str, object]
    warning: str | None


class Ffprobe:
    """ Адаптер внешнего процесса; импорт модуля ничего не запускает. """

    def __init__(self, executable: str | Path | None = None, timeout: float = 30.0) -> None:
        validate_positive(timeout, "timeout")
        if executable is not None and not isinstance(executable, (str, Path)):
            raise TypeError("ffprobe_path must be str, Path or None")
        if executable is not None and not str(executable).strip():
            raise ValueError("ffprobe_path must not be empty")
        command = "ffprobe" if executable is None else str(executable)
        # Path означает путь, даже если имя не содержит разделителя.
        if isinstance(executable, Path):
            command = str(executable.resolve())
        found = shutil.which(command)
        if found is None:
            raise FfprobeNotFoundError(f"ffprobe not found or not executable: {command}")
        self.executable = str(Path(found).resolve())
        self.timeout = timeout

    def _run(self, arguments: list[str], video: Path) -> _Response:
        """ Запустить без оболочки; техническая ошибка никогда не становится результатом. """
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
                f"ffprobe exceeded timeout of {self.timeout} s for '{video}'"
            ) from exc
        except OSError as exc:
            raise FfprobeNotFoundError(f"Failed to start ffprobe: {exc}") from exc
        except subprocess.SubprocessError as exc:
            raise VideoReadError(f"ffprobe process failed for '{video}': {exc}") from exc
        stderr = completed.stderr.strip()[:_STDERR_LIMIT]
        if completed.returncode != 0:
            raise VideoReadError(
                f"ffprobe could not read '{video}' (exit code {completed.returncode}): {stderr}"
            )
        try:
            data: object = json.loads(completed.stdout)
        except (ValueError, RecursionError) as exc:
            raise VideoReadError("ffprobe returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise VideoReadError("ffprobe output must be a JSON object")
        # Ошибки декодера отдельных кадров при нулевом коде не мешают чтению меток.
        return _Response(cast(dict[str, object], data), stderr or None)

    def video_info(self, video: Path) -> VideoInfo:
        """
        Прочитать длительность и начало шкалы первого видеопотока.

        Значения потока точнее: у части контейнеров длительность format включает
        смещение начала шкалы. Значения format используются, если у потока их нет.
        """
        response = self._run(
            [
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration,start_time:stream=index,duration,start_time",
            ],
            video,
        )
        streams = response.data.get("streams")
        if not isinstance(streams, list):
            raise VideoReadError("ffprobe output has no list of video streams")
        if not streams:
            raise VideoReadError("Video stream v:0 is missing")
        stream = streams[0]
        if not isinstance(stream, dict):
            raise VideoReadError("ffprobe stream entry is not an object")
        metadata = response.data.get("format")
        if not isinstance(metadata, dict):
            raise VideoReadError("ffprobe output has no format object")
        duration = _positive(stream.get("duration"))
        if duration is not None:
            start = _number(stream.get("start_time"))
        else:
            duration = _positive(metadata.get("duration"))
            start = None
        if start is None:
            start = _number(metadata.get("start_time"))
        return VideoInfo(duration, start or 0.0, response.warning)

    def timestamps(self, video: Path, start: float, end: float) -> FrameTimestamps:
        """ Прочитать реальные метки до абсолютного конца окна, включая ранний seek. """
        response = self._run(
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
        frames = response.data.get("frames")
        if not isinstance(frames, list):
            raise VideoReadError("ffprobe output has no list of frames")
        result: list[float | None] = []
        for frame in frames:
            if not isinstance(frame, dict):
                raise VideoReadError("ffprobe frame entry is not an object")
            result.append(_number(frame.get("best_effort_timestamp_time")))
        return FrameTimestamps(tuple(result), response.warning)
