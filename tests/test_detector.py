""" Проверки публичного API и синтетические интеграционные измерения. """

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from true_fps import (
    FfprobeTimeoutError,
    FpsDetector,
    FpsStatus,
    VideoPathError,
    VideoReadError,
    detect_fps,
)


@pytest.fixture
def process(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr("shutil.which", Mock(return_value="/tools/ffprobe"))
    mock = Mock()
    monkeypatch.setattr("subprocess.run", mock)
    return mock


def output(data: object) -> subprocess.CompletedProcess[str]:
    """ Создать ответ ffprobe для проверки оркестрации. """
    return subprocess.CompletedProcess([], 0, json.dumps(data), "")


def metadata(duration: str = "12") -> subprocess.CompletedProcess[str]:
    """ Метаданные видеопотока для модульных проверок. """
    return output({"streams": [{"index": 0}], "format": {"duration": duration}})


def frames(timestamps: list[float]) -> subprocess.CompletedProcess[str]:
    """ Кадры с заданными временными метками. """
    return output({"frames": [{"best_effort_timestamp_time": str(t)} for t in timestamps]})


def test_detector_is_reusable(process: Mock, tmp_path: Path) -> None:
    video = tmp_path / "тест с пробелами.mp4"
    video.touch()
    process.side_effect = [
        metadata(),
        frames([1, 1.04]),
        frames([6, 6.04]),
        frames([10, 10.04]),
    ] * 2
    detector = FpsDetector()
    for path in (str(video), video):
        result = detector.detect(path)
        assert result.fps == pytest.approx(25)
        assert result.is_consistent
        assert result.usable_window_count == 3
    assert detector.ffprobe_path.is_absolute()
    assert process.call_count == 8


def test_convenience_function_and_partial_data(process: Mock, tmp_path: Path) -> None:
    video = tmp_path / "video"
    video.touch()
    process.side_effect = [metadata(), frames([]), frames([6, 6.04]), frames([])]
    result = detect_fps(video)
    assert result.fps == pytest.approx(25)
    assert result.status is FpsStatus.INSUFFICIENT_DATA
    assert result.usable_window_count == 1


def test_ffprobe_warnings_are_kept_in_result(process: Mock, tmp_path: Path) -> None:
    video = tmp_path / "video"
    video.touch()
    stamps = {"frames": [{"best_effort_timestamp_time": t} for t in ("6", "6.04")]}
    broken = subprocess.CompletedProcess([], 0, json.dumps(stamps), "error while decoding MB")
    process.side_effect = [metadata(), frames([1, 1.04]), broken, frames([10, 10.04])]
    result = detect_fps(video)
    assert result.is_consistent
    assert result.warnings == ("error while decoding MB",)


def test_inconsistent_measurement_is_returned_not_raised(process: Mock, tmp_path: Path) -> None:
    video = tmp_path / "video"
    video.touch()
    process.side_effect = [metadata(), frames([1, 1.04]), frames([6, 6.02]), frames([10, 10.04])]
    result = detect_fps(video)
    assert result.fps is not None
    assert result.status is FpsStatus.INCONSISTENT


def test_unknown_duration_does_not_run_windows(process: Mock, tmp_path: Path) -> None:
    video = tmp_path / "video"
    video.touch()
    process.return_value = metadata("N/A")
    result = detect_fps(video)
    assert result.fps is None
    assert result.duration_seconds is None
    assert result.windows == ()
    assert process.call_count == 1


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("ffprobe", 30), subprocess.SubprocessError()]
)
def test_failed_window_is_not_partial_success(
    process: Mock, tmp_path: Path, failure: Exception
) -> None:
    video = tmp_path / "video"
    video.touch()
    process.side_effect = [metadata(), frames([1, 1.04]), failure]
    with pytest.raises((VideoReadError, FfprobeTimeoutError)):
        detect_fps(video)


@pytest.mark.parametrize("directory", [True, False])
def test_invalid_video_path(process: Mock, tmp_path: Path, directory: bool) -> None:
    path = tmp_path if directory else tmp_path / "missing"
    with pytest.raises(VideoPathError):
        detect_fps(path)
    process.assert_not_called()


def test_empty_video_path(process: Mock) -> None:
    with pytest.raises(ValueError):
        detect_fps("")
    process.assert_not_called()


@pytest.mark.parametrize("threshold", [-0.1, math.nan, math.inf, True])
def test_invalid_detector_threshold(threshold: float) -> None:
    with pytest.raises(ValueError):
        FpsDetector(consistency_threshold=threshold)


def test_import_has_no_process_or_tool_discovery_side_effects() -> None:
    script = """
from unittest.mock import patch
with patch("subprocess.run", side_effect=AssertionError("process")), \\
     patch("shutil.which", side_effect=AssertionError("discovery")), \\
     patch("pathlib.Path.is_file", side_effect=AssertionError("file check")):
    from true_fps import FpsDetector
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=10)


@pytest.mark.integration
@pytest.mark.parametrize("rate,offset", [("25", 0), ("30000/1001", 0), ("25", 100)])
def test_real_ffprobe(tmp_path: Path, rate: str, offset: int) -> None:
    ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if ffprobe is None or ffmpeg is None:
        pytest.skip("Нужны ffprobe и ffmpeg (ffmpeg используется только для создания видео)")
    video = tmp_path / "ролик с пробелами.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=64x64:r={rate}",
            "-t",
            "12",
            "-c:v",
            "mpeg4",
            "-g",
            "120",
            "-bf",
            "2",
            "-output_ts_offset",
            str(offset),
            "-y",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = FpsDetector(ffprobe).detect(video)
    expected = 25 if rate == "25" else 30000 / 1001
    assert result.fps == pytest.approx(expected, rel=1e-5)
    assert result.is_consistent
    assert result.usable_window_count == 3
    assert result.windows[0].start_seconds >= offset


@pytest.mark.integration
def test_real_ffprobe_single_frame_video(tmp_path: Path) -> None:
    ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if ffprobe is None or ffmpeg is None:
        pytest.skip("Нужны ffprobe и ffmpeg для создания однокадрового видео")
    video = tmp_path / "one-frame.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=25",
            "-frames:v",
            "1",
            "-c:v",
            "mpeg4",
            "-y",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = FpsDetector(ffprobe).detect(video)
    assert result.status is FpsStatus.INSUFFICIENT_DATA
    assert result.fps is None
    assert result.usable_window_count == 0


@pytest.mark.integration
def test_real_ffprobe_corrupt_file(tmp_path: Path) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe отсутствует")
    video = tmp_path / "bad.mp4"
    video.write_bytes(b"not a video")
    with pytest.raises(VideoReadError):
        detect_fps(video)
