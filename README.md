# true_fps

Независимая Python-библиотека измерения FPS по временным меткам кадров первого
видеопотока через **ffprobe**. Полезна, когда заголовочный FPS недостоверен.
Пакет и дистрибутив называются `true_fps`; исходники находятся в `src/true_fps/`.

## Установка

Нужны Python **3.10+** и отдельно установленный **ffprobe** из состава FFmpeg.
На Debian/Ubuntu: `sudo apt-get install ffmpeg`; на Windows установите сборку
FFmpeg и добавьте каталог с ffprobe в `PATH` либо передайте путь явно.
Измерение требует только ffprobe. Зависимостей Python во время исполнения нет.

### Автоустановка ffmpeg и ffprobe

`ensure_video_tools(tools_dir)` ищет оба инструмента в `<tools_dir>/ffmpeg/bin`,
затем в системном PATH. Если их нет, скачивает сборку FFmpeg для Windows x64
(gyan.dev, release essentials), извлекает `ffmpeg.exe` и `ffprobe.exe` из одного
архива и проверяет запуск. Системный PATH не меняется. На других ОС установщик
возвращает неуспешный `InstallResult` с подсказкой поставить ffmpeg пакетным
менеджером.

```python
from pathlib import Path
from true_fps import FpsDetector, ensure_video_tools

result = ensure_video_tools(Path("app_data/tools"), on_status=print)
if not result.success or result.tools is None:
    raise SystemExit(result.message)
detector = FpsDetector(result.tools.ffprobe)
```

`require_libx264=True` дополнительно требует H.264-кодировщик в ffmpeg.
Импорт пакета не запускает установку; сеть используется только при вызове.

Из локального проекта:

```sh
poetry install
poetry build
python -m pip install dist/true_fps-0.2.0-py3-none-any.whl
```

Пакет пока не опубликован в PyPI.

## Использование

```python
from pathlib import Path
from true_fps import FpsDetector, TrueFpsError

# Ищет ffprobe в PATH; допустим также ffprobe_path=Path("C:/FFmpeg/bin/ffprobe.exe").
detector = FpsDetector(timeout=30, consistency_threshold=0.01)
try:
    result = detector.detect(Path("записи/ролик с пробелами.mp4"))
except TrueFpsError as exc:
    print(f"Измерение не выполнено: {exc}")
else:
    print(result.fps, result.status.value, result.reason)
    for window in result.windows:
        print(window.fps, window.sample_count, window.reason)
```

Один детектор можно повторно использовать для разных файлов. Для одного вызова
доступна функция `detect_fps("ролик.mp4")` с теми же параметрами.
Ошибочный явный путь к ffprobe вызывает исключение без поиска замены.
Импорт пакета не запускает процессы и не проверяет инструменты или файлы.

## Результат и ошибки

`FpsResult.fps` — вычисленный FPS с исходной точностью либо `None`; это никогда
не подставленный FPS из заголовка или настроек пользователя. Округление выполняет
приложение при отображении. Значение отделено от статуса:

| Статус | Значение |
| --- | --- |
| `FpsStatus.CONSISTENT` | Пригодны хотя бы два окна, относительный разброс не больше порога |
| `FpsStatus.INCONSISTENT` | FPS вычислен, но окна расходятся; это не доказательство повреждения |
| `FpsStatus.INSUFFICIENT_DATA` | Нет пригодных окон или пригодно только одно; в последнем случае FPS сохранён |

`usable_window_count`, `relative_spread`, `reason` и `windows` позволяют оценить
полноту измерения. `warnings` содержит сообщения ffprobe, выданные при успешном
чтении (например, ошибки декодера отдельных кадров). Два согласованных окна из трёх явно обозначаются в результате.

Неверные параметры вызывают `ValueError`/`TypeError`, недоступное видео —
`VideoPathError`, отсутствующий или незапускаемый ffprobe — `FfprobeNotFoundError`.
Ошибки чтения и формата ответа — `VideoReadError`, таймаут одного вызова —
`FfprobeTimeoutError` (наследник `VideoReadError`). Все эти исключения, кроме ошибок
аргументов, наследуют `TrueFpsError`. Техническая ошибка любого окна не превращается
в частично успешный результат.

## Ограничения

- Измеряется частота **по временной шкале файла**, а не физическая частота съёмки
  камеры: ошибочные метки могут дать согласованный, но неверный FPS.
- Анализируются короткие окна около 10%, 50% и 90% длительности, **не весь файл**.
  Изменение FPS между окнами может остаться незамеченным.
- Визуальные дубликаты кадров и частота уникальных изображений не анализируются.
- Согласованность средних FPS окон не доказывает постоянную частоту каждого кадра.
- Короткое видео может не дать двух меток в каждом окне. Видео без длительности
  потока и контейнера не измеряется. Один пригодный участок не подтверждает согласованность.

## Документация

- [Алгоритм и работа с временными метками](docs/algorithm.md)
- [Публичный API и политика ошибок](docs/api.md)
- [Архитектура](docs/architecture.md)
- [Разработка, проверки и сборка](docs/development.md)
- [Перенос из fps.zip](docs/migration.md)

Лицензия [MIT](LICENSE). Copyright: Oleg Migutin, 2026.
