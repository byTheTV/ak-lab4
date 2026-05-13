"""Чтение/запись code.bin и data.bin, слова LE 32-bit"""

from __future__ import annotations

import struct
from pathlib import Path


class LoadError(ValueError):
    """Файл не кратен 4 байтам или недоступен"""


def load_words_le(path: Path) -> list[int]:
    """LE-слова из файла; длина должна делиться на 4"""
    data = path.read_bytes()
    if len(data) % 4 != 0:
        msg = f"{path}: {len(data)} байт — размер не кратен 4"
        raise LoadError(msg)
    n = len(data) // 4
    if n == 0:
        return []
    words = list(struct.unpack(f"<{n}I", data))
    return [w & 0xFFFFFFFF for w in words]


def write_words_le(path: Path, words: list[int]) -> None:
    """Запись слов LE (для транслятора и тестов)"""
    if not words:
        path.write_bytes(b"")
        return
    packed = struct.pack(f"<{len(words)}I", *[w & 0xFFFFFFFF for w in words])
    path.write_bytes(packed)
