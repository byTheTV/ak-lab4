"""Заглушка: замените на golden/integration-тесты по мере реализации."""

from ak_lab4 import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"
