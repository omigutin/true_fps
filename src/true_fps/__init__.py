"""Измерение FPS по выборочным окнам временной шкалы видео через ffprobe."""

from .detector import FpsDetector, detect_fps
from .exceptions import (
    FfprobeNotFoundError,
    FfprobeTimeoutError,
    TrueFpsError,
    VideoPathError,
    VideoReadError,
)
from .result import FpsResult, FpsStatus, WindowMeasurement

__all__ = [
    "FpsDetector",
    "FpsResult",
    "FpsStatus",
    "WindowMeasurement",
    "detect_fps",
    "TrueFpsError",
    "VideoPathError",
    "FfprobeNotFoundError",
    "VideoReadError",
    "FfprobeTimeoutError",
]
