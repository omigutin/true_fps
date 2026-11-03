""" Поиск ffmpeg и ffprobe: сначала локальный каталог инструментов, затем системный PATH. """

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Каталог исполняемых файлов внутри каталога инструментов (так раскладывает установщик).
TOOLS_BIN_DIR = Path("ffmpeg") / "bin"
# Таймаут проверочного запуска инструмента с -version, секунды.
DEFAULT_CHECK_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class VideoTools:
    """ Абсолютные пути к найденным и запускающимся ffmpeg и ffprobe. """

    ffmpeg: Path
    ffprobe: Path


def executable_name(tool: str) -> str:
    """ Имя исполняемого файла инструмента для текущей ОС (ffprobe.exe в Windows). """
    return f"{tool}.exe" if os.name == "nt" else tool


def local_tool_path(tools_dir: Path, tool: str) -> Path:
    """ Путь к инструменту в локальном каталоге инструментов. """
    return Path(tools_dir) / TOOLS_BIN_DIR / executable_name(tool)


def tool_runs(executable: Path, timeout: float = DEFAULT_CHECK_TIMEOUT) -> bool:
    """ Инструмент запускается и отвечает на -version без ошибки. """
    try:
        completed = subprocess.run(
            [str(executable), "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Незапускаемый файл — это ответ «нет», а не ошибка поиска.
        return False
    return completed.returncode == 0


def _find_tool(tool: str, tools_dir: Path | None, timeout: float) -> Path | None:
    """ Запускающийся инструмент из локального каталога или PATH. """
    if tools_dir is not None:
        local = local_tool_path(tools_dir, tool)
        if local.is_file() and tool_runs(local, timeout):
            return local.resolve()
    found = shutil.which(tool)
    if found is not None and tool_runs(Path(found), timeout):
        return Path(found).resolve()
    return None


def find_video_tools(
    tools_dir: Path | None = None, *, timeout: float = DEFAULT_CHECK_TIMEOUT
) -> VideoTools | None:
    """ Оба инструмента или None, если хотя бы один не найден или не запускается. """
    ffprobe = _find_tool("ffprobe", tools_dir, timeout)
    if ffprobe is None:
        return None
    ffmpeg = _find_tool("ffmpeg", tools_dir, timeout)
    if ffmpeg is None:
        return None
    return VideoTools(ffmpeg=ffmpeg, ffprobe=ffprobe)
