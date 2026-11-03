""" Проверки поиска ffmpeg и ffprobe в локальном каталоге и PATH. """

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from true_fps import find_video_tools, local_tool_path, video_tools


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(return_value=True)
    monkeypatch.setattr(video_tools, "tool_runs", mock)
    return mock


def make_local(tools_dir: Path, tool: str) -> Path:
    """ Создать файл инструмента в локальном каталоге. """
    path = local_tool_path(tools_dir, tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bin")
    return path


def test_local_tools_have_priority(
    tmp_path: Path, runs: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe = make_local(tmp_path, "ffmpeg"), make_local(tmp_path, "ffprobe")
    monkeypatch.setattr("shutil.which", Mock(side_effect=AssertionError("PATH")))
    tools = find_video_tools(tmp_path)
    assert tools is not None
    assert (tools.ffmpeg, tools.ffprobe) == (ffmpeg.resolve(), ffprobe.resolve())


def test_path_is_used_without_local_tools(
    tmp_path: Path, runs: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda tool: str(tmp_path / tool))
    tools = find_video_tools(tmp_path / "missing")
    assert tools is not None and tools.ffprobe.name == "ffprobe"


def test_broken_local_tool_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_local(tmp_path, "ffmpeg")
    make_local(tmp_path, "ffprobe")
    system = tmp_path / "system"
    monkeypatch.setattr("shutil.which", lambda tool: str(system / tool))
    monkeypatch.setattr(video_tools, "tool_runs", lambda path, timeout: system in path.parents)
    tools = find_video_tools(tmp_path)
    assert tools is not None and system in tools.ffmpeg.parents


def test_missing_tool_returns_none(runs: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda tool: None if tool == "ffmpeg" else "/x/" + tool)
    assert find_video_tools() is None


@pytest.mark.parametrize("error", [OSError("denied"), subprocess.TimeoutExpired("x", 1)])
def test_tool_that_cannot_start_does_not_run(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr("subprocess.run", Mock(side_effect=error))
    assert video_tools.tool_runs(Path("ffprobe")) is False


def test_tool_runs_by_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("subprocess.run", Mock(return_value=subprocess.CompletedProcess([], 1)))
    assert video_tools.tool_runs(Path("ffprobe")) is False
