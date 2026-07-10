from __future__ import annotations

import re

MICROSECOND_UNITS = {"us", "µs", "μs"}


def normalize_time_step(value: float, unit: str) -> tuple[float, str]:
    unit = unit.lower()
    factors_to_ps = {"fs": 0.001, "ps": 1.0, "ns": 1000.0}
    if unit in MICROSECOND_UNITS:
        return value * 1_000_000.0, "ps"
    if unit not in factors_to_ps:
        raise ValueError(f"Unsupported time-step unit: {unit}")
    return value * factors_to_ps[unit], "ps"


def normalize_duration(value: float, unit: str) -> tuple[float, str]:
    unit = unit.lower()
    factors_to_ns = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0}
    if unit in MICROSECOND_UNITS:
        return value * 1000.0, "ns"
    if unit not in factors_to_ns:
        raise ValueError(f"Unsupported duration unit: {unit}")
    return value * factors_to_ns[unit], "ns"


def normalize_temperature(value: float, unit: str) -> tuple[float, str]:
    canonical = unit.lower().replace("°", "")
    if canonical in {"k", "kelvin"}:
        return value, "K"
    if canonical in {"c", "celsius"}:
        return value + 273.15, "K"
    raise ValueError(f"Unsupported temperature unit: {unit}")


def normalize_pressure(value: float, unit: str) -> tuple[float, str]:
    canonical = unit.lower()
    if canonical == "bar":
        return value, "bar"
    if canonical == "atm":
        return value * 1.01325, "bar"
    if canonical == "pa":
        return value / 100_000.0, "bar"
    raise ValueError(f"Unsupported pressure unit: {unit}")


def parse_number(text: str) -> float:
    return float(re.sub(r",", "", text))


def format_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 8)
