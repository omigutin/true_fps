# Разработка

Требуются Python 3.10+ и Poetry 2.2+ (в облачной среде проверено с Python 3.12
и Poetry 2.5.1). Минимальная версия задана явно; синтаксис и типы проверяются
в режиме Python 3.10. Фактический запуск на всех версиях Python и Windows требует
отдельной матрицы CI и не заявляется по одному запуску в Linux.

```sh
poetry config virtualenvs.in-project true --local
poetry install --no-interaction
poetry run pytest
poetry run ruff check .
poetry run mypy
poetry check --lock
poetry build
```

`ruff format` не используется: он убирает пробелы внутри однострочных докстрингов,
а в проекте принят вид `""" Текст. """`.

`poetry.lock` хранится в Git; `poetry install` использует зафиксированные версии.
`poetry lock` нужен при сознательном изменении зависимостей. Для автоматизации
вместо локального файла конфигурации можно задать `POETRY_VIRTUALENVS_IN_PROJECT=true`.

Модульные тесты не требуют ffprobe:

```sh
poetry run pytest -m 'not integration'
```

Интеграционные проверки:

```sh
poetry run pytest -m integration
```

Они используют ffprobe, а для создания синтетического MPEG-4-видео — ffmpeg.
При отсутствии инструментов pytest явно пропускает соответствующие проверки.
Проверяются целый и дробный FPS, seek при длинных GOP, B-кадры, путь с кириллицей
и пробелами, сдвинутая временная шкала, нехватка меток однокадрового видео,
а также отказ на файле, который не является видео. Видеофайлы создаются
временными и не коммитятся. Для исправлений реальных записей нужны отдельные
репрезентативные данные, которых в `fps.zip` нет.

Проверка установленного колеса вне исходников:

```sh
python -m venv /tmp/true-fps-wheel
/tmp/true-fps-wheel/bin/python -m pip install --no-deps dist/true_fps-0.2.0-py3-none-any.whl
cd /tmp
/tmp/true-fps-wheel/bin/python -c 'from true_fps import FpsDetector; from importlib.resources import files; assert files("true_fps").joinpath("py.typed").is_file()'
```

В Windows соответствующие команды виртуального окружения находятся в `Scripts`.
Сборка создаёт wheel и sdist в `dist/`, MIT-лицензия входит в оба артефакта.
Публикация пакета и push выполняются только по отдельному указанию.
