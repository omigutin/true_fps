""" Проверки установщика: один архив, атомарная установка, проверки комплекта. """

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from true_fps import InstallResult, VideoTools, ensure_video_tools, install_video_tools, installer

PREFIX = "ffmpeg-7.0-essentials_build/bin"
FULL = {f"{PREFIX}/ffmpeg.exe": b"FFMPEG-BIN", f"{PREFIX}/ffprobe.exe": b"FFPROBE-BIN"}


def archive(members: dict[str, bytes]) -> bytes:
    """ Zip-архив с заданными файлами. """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for name, data in members.items():
            target.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")


def stub(
    monkeypatch: pytest.MonkeyPatch,
    members: dict[str, bytes] = FULL,
    run_ok: bool = True,
    libx264: bool = True,
) -> None:
    """ Подменить загрузку и проверочные запуски. """
    monkeypatch.setattr(installer, "_download", lambda url, status: archive(members))
    monkeypatch.setattr(installer, "tool_runs", lambda path: run_ok)
    monkeypatch.setattr(installer, "has_libx264", lambda path: libx264)


def final(tools_dir: Path) -> tuple[Path, Path]:
    """ Итоговые пути обоих файлов. """
    bin_dir = tools_dir / "ffmpeg" / "bin"
    return bin_dir / "ffmpeg.exe", bin_dir / "ffprobe.exe"


def test_installs_both_tools_from_one_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub(monkeypatch)
    messages: list[str] = []
    result = install_video_tools(tmp_path, on_status=messages.append)
    ffmpeg, ffprobe = final(tmp_path)
    assert result.success and result.tools is not None
    assert ffmpeg.read_bytes() == b"FFMPEG-BIN" and ffprobe.read_bytes() == b"FFPROBE-BIN"
    assert messages and not (tmp_path / ".staging_ffmpeg").exists()


def test_partial_install_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ffmpeg, ffprobe = final(tmp_path)
    ffprobe.parent.mkdir(parents=True)
    ffprobe.write_bytes(b"OLD")
    stub(monkeypatch)
    assert install_video_tools(tmp_path).success
    assert ffprobe.read_bytes() == b"FFPROBE-BIN" and ffmpeg.is_file()


def test_healthy_install_is_not_downloaded_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg, ffprobe = final(tmp_path)
    ffmpeg.parent.mkdir(parents=True)
    ffmpeg.write_bytes(b"A")
    ffprobe.write_bytes(b"B")
    stub(monkeypatch)

    def fail(url: str, status: Any) -> bytes:
        raise AssertionError("download")

    monkeypatch.setattr(installer, "_download", fail)
    result = install_video_tools(tmp_path)
    assert result.success and "уже установлен" in result.message


@pytest.mark.parametrize("missing", ["ffmpeg.exe", "ffprobe.exe"])
def test_archive_without_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    stub(monkeypatch, {k: v for k, v in FULL.items() if not k.endswith(missing)})
    result = install_video_tools(tmp_path)
    assert not result.success and f"{missing} не найден в архиве" in result.message


def test_tool_that_does_not_run_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub(monkeypatch, run_ok=False)
    result = install_video_tools(tmp_path)
    assert not result.success and "не запускается" in result.message
    assert not final(tmp_path)[0].exists()


def test_libx264_is_checked_only_on_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub(monkeypatch, libx264=False)
    assert install_video_tools(tmp_path).success
    stub(monkeypatch, libx264=False)
    final(tmp_path)[0].unlink()
    result = install_video_tools(tmp_path, require_libx264=True)
    assert not result.success and "libx264" in result.message


def test_checksum_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch)
    result = install_video_tools(tmp_path, sha256="0" * 64)
    assert not result.success and "Контрольная сумма" in result.message


def test_other_os_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    result = install_video_tools(tmp_path)
    assert not result.success and "Windows" in result.message


def test_ensure_does_not_install_found_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = VideoTools(Path("/x/ffmpeg"), Path("/x/ffprobe"))
    monkeypatch.setattr(installer, "find_video_tools", lambda tools_dir: tools)
    monkeypatch.setattr(installer, "install_video_tools", None)
    assert ensure_video_tools(tmp_path).tools == tools


def test_ensure_installs_missing_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = VideoTools(Path("/x/ffmpeg"), Path("/x/ffprobe"))
    found = iter((None, tools))
    monkeypatch.setattr(installer, "find_video_tools", lambda tools_dir: next(found))
    monkeypatch.setattr(
        installer, "install_video_tools", lambda *a, **k: InstallResult(True, "ok", tools)
    )
    assert ensure_video_tools(tmp_path) == InstallResult(True, "ok", tools)


def test_ensure_reports_failed_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "find_video_tools", lambda tools_dir: None)
    monkeypatch.setattr(
        installer, "install_video_tools", lambda *a, **k: InstallResult(False, "нет сети")
    )
    assert ensure_video_tools(tmp_path) == InstallResult(False, "нет сети")


def test_progress_line_has_size_percent_and_speed() -> None:
    progress = installer.DownloadProgress(5 * 1024 * 1024, 10 * 1024 * 1024, 2.0)
    line = installer.format_progress(progress)
    assert "5.0 МБ / 10.0 МБ" in line and "(50%)" in line and "2.5 МБ/с" in line


def test_network_error_message_keeps_reason() -> None:
    message = installer._network_error_message("https://example.test/a.zip", OSError("blocked"))
    assert "OSError: blocked" in message and "прокси" in message


def test_download_has_no_total_time_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        """ Медленный ответ, который продолжает отдавать данные. """

        headers = {"Content-Length": "6"}

        def __init__(self) -> None:
            self._chunks = iter((b"abc", b"def", b""))

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            return next(self._chunks)

    stamps = iter((0.0, 400.0, 800.0, 800.0, 800.0))
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())
    monkeypatch.setattr("time.monotonic", lambda: next(stamps))
    assert installer._download("https://example.test/a.zip", lambda line: None) == b"abcdef"
