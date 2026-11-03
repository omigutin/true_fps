""" Проверки модели результата и явного публичного интерфейса. """

from dataclasses import FrozenInstanceError

import pytest

from true_fps import FpsResult, FpsStatus, WindowMeasurement


def test_result_is_immutable_and_does_not_substitute_fps() -> None:
    result = FpsResult(None, FpsStatus.INSUFFICIENT_DATA, None, (), None, "Нет меток")
    with pytest.raises(FrozenInstanceError):
        result.fps = 0  # type: ignore[misc]
    assert result.fps is None
    assert result.usable_window_count == 0
    assert not result.is_consistent


def test_window_diagnostics() -> None:
    window = WindowMeasurement(0, 1, 26, 0, 0, 1, 25)
    assert window.interval_count == 25
    assert window.elapsed_seconds == 1
