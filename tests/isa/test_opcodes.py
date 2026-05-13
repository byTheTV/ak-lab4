from __future__ import annotations

from ak_lab4.isa import Opcode


def test_all_opcodes_distinct() -> None:
    values = [m.value for m in Opcode]
    assert len(values) == len(set(values))
