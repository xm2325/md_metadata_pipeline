import pytest

from mdlit.normalization import (
    normalize_duration,
    normalize_pressure,
    normalize_temperature,
    normalize_time_step,
)


def test_time_step_fs_to_ps() -> None:
    assert normalize_time_step(2, "fs") == (0.002, "ps")


def test_duration_microseconds_to_ns() -> None:
    assert normalize_duration(1.5, "µs") == (1500.0, "ns")


def test_temperature_celsius_to_kelvin() -> None:
    value, unit = normalize_temperature(25, "Celsius")
    assert value == pytest.approx(298.15)
    assert unit == "K"


def test_pressure_atm_to_bar() -> None:
    value, unit = normalize_pressure(1, "atm")
    assert value == pytest.approx(1.01325)
    assert unit == "bar"


def test_unsupported_unit() -> None:
    with pytest.raises(ValueError):
        normalize_duration(1, "minute")
