"""Минимальная проверка пакета. Интеграционные golden — см. ``test_golden_phase_a.py``."""

from ak_lab4 import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"
