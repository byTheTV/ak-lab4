"""Загрузка сегментов `code.bin` / `data.bin` (LE 32-бит слова)."""

from __future__ import annotations

import struct
from pathlib import Path


class LoadError(ValueError):
    """Некорректный размер файла или путь."""


def load_words_le(path: Path) -> list[int]:
    """
    Прочитать файл как последовательность 32-бит слов (little-endian).

    Длина файла должна быть кратна 4 байтам.
    """
    data = path.read_bytes()
    if len(data) % 4 != 0:
        msg = f"Размер {path} ({len(data)} байт) не кратен 4"
        raise LoadError(msg)
    n = len(data) // 4
    if n == 0:
        return []
    words = list(struct.unpack(f"<{n}I", data))
    return [w & 0xFFFFFFFF for w in words]


def write_words_le(path: Path, words: list[int]) -> None:
    """Записать слова в файл в LE (для тестов и отладки)."""
    if not words:
        path.write_bytes(b"")
        return
    packed = struct.pack(f"<{len(words)}I", *[w & 0xFFFFFFFF for w in words])
    path.write_bytes(packed)
