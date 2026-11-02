"""Исключения на границе внешнего инструмента и входных файлов."""


class TrueFpsError(Exception):
    """Базовая ошибка измерения, кроме ошибок аргументов Python."""


class VideoPathError(TrueFpsError):
    """Видео не существует, недоступно или не является обычным файлом."""


class FfprobeNotFoundError(TrueFpsError):
    """Явно указанный инструмент или команда из PATH недоступны."""


class VideoReadError(TrueFpsError):
    """ffprobe не смог прочитать видео или выдал некорректный ответ."""


class FfprobeTimeoutError(VideoReadError):
    """Один вызов ffprobe превысил установленный таймаут."""
