"""
Автоматическая установка ffmpeg и ffprobe в локальный каталог инструментов.

Скачивается одна сборка FFmpeg для Windows x64, из неё извлекаются оба файла
(одна версия) в ``<tools_dir>/ffmpeg/bin``. Системный PATH не меняется.
Комплект считается установленным, только если оба файла запускаются.
"""

import hashlib
import io
import os
import platform
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .video_tools import (
    DEFAULT_CHECK_TIMEOUT,
    TOOLS_BIN_DIR,
    VideoTools,
    find_video_tools,
    tool_runs,
)

# Официальный источник сборок FFmpeg для Windows (версия «release essentials»).
FFMPEG_BUNDLE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
# Таймаут ожидания очередного блока при загрузке, секунды (общее время не ограничено).
_DOWNLOAD_TIMEOUT = 180
# Размер блока чтения при загрузке, байты.
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
# Как часто сообщать о ходе загрузки, секунды.
_PROGRESS_INTERVAL = 1.0
# Имя временного каталога распаковки внутри каталога инструментов.
_STAGING_NAME = ".staging_ffmpeg"
# Заголовок User-Agent запроса загрузки.
_USER_AGENT = "true-fps-installer"
# Файлы комплекта: суффикс пути внутри архива → имя файла в каталоге bin.
_BUNDLE_MEMBERS = {"bin/ffmpeg.exe": "ffmpeg.exe", "bin/ffprobe.exe": "ffprobe.exe"}

StatusCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class InstallResult:
    """ Итог проверки или установки: успех, сообщение для пользователя и пути инструментов. """

    success: bool
    message: str
    tools: VideoTools | None = None


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    """ Текущее состояние загрузки архива. """

    downloaded_bytes: int
    total_bytes: int | None
    elapsed_seconds: float

    @property
    def bytes_per_second(self) -> float:
        """ Средняя скорость загрузки, байт в секунду. """
        return self.downloaded_bytes / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0


def _silent(_: str) -> None:
    """ Обработчик статуса по умолчанию: ничего не выводит. """


def ensure_video_tools(
    tools_dir: Path,
    *,
    require_libx264: bool = False,
    on_status: StatusCallback | None = None,
    url: str = FFMPEG_BUNDLE_URL,
    sha256: str | None = None,
) -> InstallResult:
    """
    Найти ffmpeg и ffprobe (локальный каталог, затем PATH), а если их нет — установить.

    require_libx264: ffmpeg должен уметь кодировать H.264 (нужно для записи видео).
    """
    tools = find_video_tools(tools_dir)
    if tools is not None and (not require_libx264 or has_libx264(tools.ffmpeg)):
        return InstallResult(True, "Видеоинструменты (ffmpeg, ffprobe) найдены.", tools)
    result = install_video_tools(
        tools_dir, require_libx264=require_libx264, on_status=on_status, url=url, sha256=sha256
    )
    if not result.success:
        return result
    tools = find_video_tools(tools_dir)
    if tools is None:
        return InstallResult(False, "Видеоинструменты установлены, но не запускаются.")
    return InstallResult(True, result.message, tools)


def install_video_tools(
    tools_dir: Path,
    *,
    require_libx264: bool = False,
    on_status: StatusCallback | None = None,
    url: str = FFMPEG_BUNDLE_URL,
    sha256: str | None = None,
) -> InstallResult:
    """ Скачать сборку и атомарно установить оба инструмента; повторный запуск безопасен. """
    status = on_status or _silent
    bin_dir = Path(tools_dir) / TOOLS_BIN_DIR
    ffmpeg_final, ffprobe_final = bin_dir / "ffmpeg.exe", bin_dir / "ffprobe.exe"

    if ffmpeg_final.is_file() and ffprobe_final.is_file():
        problem = _health_problem(ffmpeg_final, ffprobe_final, require_libx264)
        if problem is None:
            return InstallResult(
                True,
                f"Комплект уже установлен и исправен: {bin_dir}",
                VideoTools(ffmpeg_final.resolve(), ffprobe_final.resolve()),
            )
        status(f"[FFmpeg] переустановка — обнаружена проблема: {problem}")

    if platform.system() != "Windows":
        return InstallResult(
            False,
            "Автоустановка ffmpeg/ffprobe доступна только в Windows x64. "
            "Установите ffmpeg пакетным менеджером (например, apt install ffmpeg).",
        )

    status(f"[FFmpeg] загрузка: {url}")
    try:
        data = _download(url, status)
    except urllib.error.HTTPError as exc:
        return InstallResult(False, _http_error_message(url, exc))
    except urllib.error.URLError as exc:
        return InstallResult(False, _network_error_message(url, exc.reason))
    except TimeoutError as exc:
        return InstallResult(False, f"Истёк тайм-аут загрузки с {url}: {exc}")
    except ssl.SSLError as exc:
        return InstallResult(False, f"Ошибка TLS/SSL при подключении к {url}: {exc}")
    except OSError as exc:
        return InstallResult(False, f"Системная ошибка при загрузке с {url}: {exc}")

    digest = hashlib.sha256(data).hexdigest()
    if sha256 is not None and digest.lower() != sha256.lower():
        return InstallResult(
            False, f"Контрольная сумма не совпала (ожидался {sha256}, получен {digest})"
        )
    status(f"[FFmpeg] SHA-256 архива: {digest}")

    staging = Path(tools_dir) / _STAGING_NAME
    _remove_dir(staging)
    try:
        problem = _stage_members(data, staging)
        if problem is not None:
            return InstallResult(False, problem)
        staged_ffmpeg, staged_ffprobe = staging / "ffmpeg.exe", staging / "ffprobe.exe"
        status("[FFmpeg] проверка запуска инструментов...")
        problem = _health_problem(staged_ffmpeg, staged_ffprobe, require_libx264)
        if problem is not None:
            return InstallResult(False, problem)
        bin_dir.mkdir(parents=True, exist_ok=True)
        os.replace(staged_ffmpeg, ffmpeg_final)
        os.replace(staged_ffprobe, ffprobe_final)
    finally:
        _remove_dir(staging)

    status(f"[FFmpeg] установлено в {bin_dir}")
    return InstallResult(
        True,
        "Видеоинструменты (ffmpeg, ffprobe) установлены автоматически.",
        VideoTools(ffmpeg_final.resolve(), ffprobe_final.resolve()),
    )


def has_libx264(ffmpeg: Path, timeout: float = DEFAULT_CHECK_TIMEOUT) -> bool:
    """ В сборке ffmpeg есть H.264-кодировщик libx264. """
    try:
        completed = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-h", "encoder=libx264"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Незапускаемый ffmpeg не содержит кодировщика — это ответ, а не сбой проверки.
        return False
    output = f"{completed.stdout}\n{completed.stderr}"
    return "Encoder libx264" in output and "Unknown encoder" not in output


def _health_problem(ffmpeg: Path, ffprobe: Path, require_libx264: bool) -> str | None:
    """ Текст первой проблемы комплекта или None. """
    if not ffmpeg.is_file():
        return "ffmpeg.exe не найден в архиве"
    if not ffprobe.is_file():
        return "ffprobe.exe не найден в архиве"
    if not tool_runs(ffmpeg):
        return "ffmpeg.exe не запускается"
    if not tool_runs(ffprobe):
        return "ffprobe.exe не запускается"
    if require_libx264 and not has_libx264(ffmpeg):
        return "libx264 отсутствует в ffmpeg (H.264-кодировщик недоступен)"
    return None


def _stage_members(archive_bytes: bytes, staging: Path) -> str | None:
    """ Извлечь оба файла из архива во временный каталог; текст ошибки или None. """
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = archive.namelist()
            for suffix, target_name in _BUNDLE_MEMBERS.items():
                source = next((n for n in names if n.replace("\\", "/").endswith(suffix)), None)
                if source is None:
                    return f"{target_name} не найден в архиве"
                staging.mkdir(parents=True, exist_ok=True)
                with archive.open(source) as reader, (staging / target_name).open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
    except zipfile.BadZipFile as exc:
        return f"Архив повреждён: {exc}"
    return None


def _download(url: str, status: StatusCallback) -> bytes:
    """ Загрузить архив блоками, сообщая о ходе загрузки. """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:  # noqa: S310
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header and total_header.isdigit() else None
        started = time.monotonic()
        last_report = started
        buffer = io.BytesIO()
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
            now = time.monotonic()
            if not chunk:
                break
            buffer.write(chunk)
            if now - last_report >= _PROGRESS_INTERVAL:
                status(format_progress(DownloadProgress(buffer.tell(), total, now - started)))
                last_report = now
        status(format_progress(DownloadProgress(buffer.tell(), total, time.monotonic() - started)))
        return buffer.getvalue()


def format_bytes(value: float) -> str:
    """ Размер данных в понятных человеку единицах. """
    units = ("Б", "КБ", "МБ", "ГБ")
    size = float(value)
    for unit in units[:-1]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {units[-1]}"


def format_progress(progress: DownloadProgress) -> str:
    """ Строка хода загрузки: объём, процент и скорость. """
    downloaded = format_bytes(progress.downloaded_bytes)
    speed = format_bytes(progress.bytes_per_second)
    if progress.total_bytes:
        percent = min(progress.downloaded_bytes / progress.total_bytes * 100, 100.0)
        return (
            f"[Загрузка] {downloaded} / {format_bytes(progress.total_bytes)} "
            f"({percent:.0f}%), {speed}/с, {progress.elapsed_seconds:.0f} с."
        )
    return f"[Загрузка] {downloaded}, {speed}/с, {progress.elapsed_seconds:.0f} с."


def _http_error_message(url: str, error: urllib.error.HTTPError) -> str:
    """ Сообщение об HTTP-ошибке сервера. """
    return (
        f"Сервер вернул HTTP {error.code} {error.reason} при загрузке {url}. "
        "Проверьте доступность адреса, настройки прокси и ограничения сети."
    )


def _network_error_message(url: str, reason: object) -> str:
    """ Сообщение о сетевой ошибке подключения. """
    return (
        f"Сетевая ошибка при загрузке {url}: {type(reason).__name__}: {reason}. "
        "Проверьте DNS, прокси, межсетевой экран, антивирус и доступ в интернет."
    )


def _remove_dir(path: Path) -> None:
    """ Удалить временный каталог; заблокированные файлы не прерывают установку. """
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
