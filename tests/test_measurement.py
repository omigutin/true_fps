""" Проверки формул и пограничных временных шкал без внешних инструментов. """

import math

import pytest

from true_fps import FpsStatus
from true_fps.measurement import build_windows, combine_windows, measure_window


def test_uniform_fractional_fps_keeps_precision() -> None:
    rate = 30000 / 1001
    window = measure_window(0, 5, [i / rate for i in range(100)])
    assert window.fps == pytest.approx(rate, abs=1e-12)
    assert window.fps != round(rate, 4)
    assert window.interval_count == 99


def test_weighted_combination_is_not_average_of_rates() -> None:
    first = measure_window(0, 1, [0, 0.5, 1])
    second = measure_window(2, 5, [2, 3, 4, 5])
    result = combine_windows(6, [first, second], 0.01)
    assert result.fps == pytest.approx(5 / 4)
    assert result.fps != 1.5
    assert result.relative_spread == pytest.approx(1 / 1.5)
    assert result.status is FpsStatus.INCONSISTENT


@pytest.mark.parametrize("second_rate,expected", [(25.1, True), (26, False)])
def test_consistency_threshold(second_rate: float, expected: bool) -> None:
    windows = [
        measure_window(0, 1, [i / 25 for i in range(20)]),
        measure_window(2, 3, [2 + i / second_rate for i in range(20)]),
    ]
    result = combine_windows(4, windows, 0.01)
    assert result.is_consistent is expected


def test_spread_equal_to_threshold_is_accepted() -> None:
    windows = [measure_window(0, 1, [0, 0.5, 1]), measure_window(2, 3, [2, 3])]
    assert combine_windows(4, windows, 2 / 3).is_consistent


@pytest.mark.parametrize(
    "timestamps",
    [
        [],
        [0.0],
        [0.0, 0.0],
        [0.0, 0.5, 0.5, 1.0],
        [0.5, 0.0, 1.0],
        [0.0, None, 1.0],
        [0.0, math.nan, 1.0],
        [0.0, math.inf, 1.0],
    ],
)
def test_unusable_timestamps(timestamps: list[float | None]) -> None:
    window = measure_window(0, 2, timestamps)
    assert window.fps is None
    assert window.reason
    assert window.interval_count == 0
    assert window.elapsed_seconds == 0


def test_seek_before_requested_start_is_filtered() -> None:
    window = measure_window(10, 12, [8, 9, 10, 10.5, 11, 11.5, 12, 13])
    assert window.sample_count == 5
    assert window.first_timestamp == 10
    assert window.last_timestamp == 12
    assert window.fps == 2


def test_partially_read_window_uses_actual_elapsed_time() -> None:
    window = measure_window(10, 15, [12, 12.04, 12.08])
    assert window.fps == pytest.approx(25)
    assert window.elapsed_seconds == pytest.approx(0.08)


def test_one_window_never_confirms_consistency() -> None:
    result = combine_windows(12, [measure_window(0, 1, [0, 0.04])], 0.01)
    assert result.fps == 25
    assert result.status is FpsStatus.INSUFFICIENT_DATA
    assert result.relative_spread is None
    assert result.usable_window_count == 1
    assert not result.is_consistent


def test_partially_successful_windows_retain_diagnostics() -> None:
    windows = [
        measure_window(0, 1, [0, 0.04]),
        measure_window(2, 3, []),
        measure_window(4, 5, [4, 4.04]),
    ]
    result = combine_windows(6, windows, 0.01)
    assert result.is_consistent
    assert result.usable_window_count == 2
    assert len(result.windows) == 3
    assert result.windows[1].reason
    assert "2 из 3" in result.reason


def test_no_windows_is_absence_not_zero() -> None:
    result = combine_windows(0.01, [], 0.01)
    assert result.fps is None
    assert result.status is FpsStatus.INSUFFICIENT_DATA


@pytest.mark.parametrize("duration", [0.001, 0.1, 1.0, 12.0, 60.0, 10000.0])
def test_windows_are_bounded_and_nonoverlapping(duration: float) -> None:
    windows = build_windows(duration)
    assert len(windows) == 3
    for start, end in windows:
        assert 0 <= start < end <= duration
        assert end - start == pytest.approx(min(5, duration / 6))
    assert all(right <= left for (_, right), (left, _) in zip(windows, windows[1:], strict=False))


def test_window_centers_and_timeline_origin() -> None:
    windows = build_windows(60, 100)
    assert windows == ((103.5, 108.5), (127.5, 132.5), (151.5, 156.5))


@pytest.mark.parametrize("duration", [0, -1, math.nan, math.inf, -math.inf, True])
def test_invalid_duration(duration: float) -> None:
    with pytest.raises(ValueError):
        build_windows(duration)


@pytest.mark.parametrize("threshold", [-1, math.nan, math.inf, True])
def test_invalid_threshold(threshold: float) -> None:
    with pytest.raises(ValueError):
        combine_windows(12, [], threshold)


@pytest.mark.parametrize(
    "timestamps",
    [
        [0.0, 0.5, 1.0, 1.5, 2.0, None, None],  # досброс декодера в конце чтения
        [None, 0.0, 0.5, 1.0, 1.5, 2.0],  # кадр раннего seek без метки
        [8.0, None, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0, math.nan],  # вне окна с обеих сторон
    ],
)
def test_missing_timestamps_outside_window_span_are_ignored(
    timestamps: list[float | None],
) -> None:
    window = measure_window(0, 2, timestamps)
    assert window.fps == pytest.approx(2.0)
    assert window.reason is None
    assert window.sample_count == 5
    assert window.invalid_count == sum(1 for v in timestamps if v is None or not math.isfinite(v))


def test_missing_timestamp_inside_window_span_rejects_window() -> None:
    window = measure_window(0, 2, [0.0, 0.5, None, 1.5, 2.0, None])
    assert window.fps is None
    assert window.reason
    assert window.invalid_count == 2
