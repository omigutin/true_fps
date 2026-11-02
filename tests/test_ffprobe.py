"""Проверки границы subprocess, поиска исполняемого файла и JSON."""

import json
import math
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from true_fps import FfprobeNotFoundError, FfprobeTimeoutError, VideoReadError
from true_fps.ffprobe import Ffprobe


@pytest.fixture
def process(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr("shutil.which", Mock(return_value="/tools/ffprobe"))
    mock = Mock(return_value=subprocess.CompletedProcess([], 0, "{}", ""))
    monkeypatch.setattr("subprocess.run", mock)
    return mock


def answer(process: Mock, data: object) -> None:
    """Настроить успешный ответ на границе процесса."""
    process.return_value = subprocess.CompletedProcess([], 0, json.dumps(data), "")


def test_paths_with_spaces_and_cyrillic_are_separate_arguments(process: Mock) -> None:
    answer(process, {"frames": [{"best_effort_timestamp_time": "1.25"}]})
    probe = Ffprobe("мой ffprobe", timeout=7)
    video = Path("папка с пробелами/ролик ; $(echo).mp4")
    assert probe.timestamps(video, 1, 2) == (1.25,)
    args, kwargs = process.call_args
    assert args[0][-1] == str(video)
    assert "shell" not in kwargs
    assert kwargs["timeout"] == 7
    assert "v:0" in args[0]
    assert "1.000000000%2.000000000" in args[0]


@pytest.mark.parametrize("duration", ["N/A", "nan", "inf", "-inf", "oops", "0", -1, None, True])
def test_invalid_duration_is_missing_data(process: Mock, duration: object) -> None:
    answer(process, {"streams": [{"index": 0}], "format": {"duration": duration}})
    assert Ffprobe().video_info(Path("video")).duration is None


def test_valid_metadata_and_origin(process: Mock) -> None:
    answer(process, {"streams": [{"index": 0}], "format": {"duration": "12", "start_time": "5"}})
    info = Ffprobe().video_info(Path("video"))
    assert info.duration == 12
    assert info.start_time == 5


def test_bad_timestamps_preserve_missing_frame_positions(process: Mock) -> None:
    values: list[object] = ["0", "N/A", "bad", "inf", "nan", True, None, "0.04"]
    answer(process, {"frames": [{"best_effort_timestamp_time": value} for value in values]})
    assert Ffprobe().timestamps(Path("video"), 0, 1) == (
        0,
        None,
        None,
        None,
        None,
        None,
        None,
        0.04,
    )


def test_frame_without_timestamp_is_not_silently_deleted(process: Mock) -> None:
    answer(process, {"frames": [{}]})
    assert Ffprobe().timestamps(Path("video"), 0, 1) == (None,)


@pytest.mark.parametrize("payload", ["not JSON", "[]", '{"frames": null}', '{"frames": [1]}'])
def test_invalid_output_raises(process: Mock, payload: str) -> None:
    process.return_value = subprocess.CompletedProcess([], 0, payload, "")
    with pytest.raises(VideoReadError):
        Ffprobe().timestamps(Path("video"), 0, 1)


@pytest.mark.parametrize("payload", [{}, {"streams": []}, {"streams": [0]}, {"streams": None}])
def test_missing_video_or_format_raises(process: Mock, payload: object) -> None:
    answer(process, payload)
    with pytest.raises(VideoReadError):
        Ffprobe().video_info(Path("video"))


@pytest.mark.parametrize("returncode", [0, 1])
def test_error_stderr_is_not_success(process: Mock, returncode: int) -> None:
    process.return_value = subprocess.CompletedProcess(
        [], returncode, '{"frames": []}', "decode error"
    )
    with pytest.raises(VideoReadError, match="decode error"):
        Ffprobe().timestamps(Path("video"), 0, 1)


def test_nonzero_exit_without_stderr_raises(process: Mock) -> None:
    process.return_value = subprocess.CompletedProcess([], 1, "{}", "")
    with pytest.raises(VideoReadError):
        Ffprobe().video_info(Path("video"))


def test_timeout_is_specific_error(process: Mock) -> None:
    process.side_effect = subprocess.TimeoutExpired("ffprobe", 1)
    with pytest.raises(FfprobeTimeoutError):
        Ffprobe().timestamps(Path("video"), 0, 1)


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError()])
def test_tool_removed_or_not_executable(process: Mock, error: OSError) -> None:
    process.side_effect = error
    with pytest.raises(FfprobeNotFoundError):
        Ffprobe().video_info(Path("video"))


def test_subprocess_failure(process: Mock) -> None:
    process.side_effect = subprocess.SubprocessError("failure")
    with pytest.raises(VideoReadError):
        Ffprobe().video_info(Path("video"))


@pytest.mark.parametrize("explicit", [None, "missing", Path("missing")])
def test_missing_tool_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, explicit: str | Path | None
) -> None:
    lookup = Mock(return_value=None)
    monkeypatch.setattr("shutil.which", lookup)
    with pytest.raises(FfprobeNotFoundError):
        Ffprobe(explicit)
    assert lookup.call_count == 1
    if explicit is not None:
        assert lookup.call_args.args[0] != "ffprobe"


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, True])
def test_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ValueError):
        Ffprobe(timeout=timeout)


def test_empty_explicit_path() -> None:
    with pytest.raises(ValueError):
        Ffprobe("")
