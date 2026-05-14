"""Размеры IM/DM по спеке v0"""

from __future__ import annotations

# DM: слова по 16-битному адресному полю
DM_SIZE_WORDS: int = 65536
# IM: фиксированный размер памяти инструкций
IM_SIZE_WORDS: int = 65536
# дно стека - следующая свободная ячейка сверху
STACK_BASE: int = 0x1000
