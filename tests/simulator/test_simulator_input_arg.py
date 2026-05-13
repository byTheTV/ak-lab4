from __future__ import annotations

import io
import sys

import pytest

from ak_lab4.cpu import Cpu
from ak_lab4.isa import Opcode, Port, pack_word
from ak_lab4.loader import write_words_le
from ak_lab4.simulator.__main__ import apply_input_to_cpu
from ak_lab4.simulator.__main__ import main as simulator_main


def test_apply_input_from_file(tmp_path) -> None:
    p = tmp_path / "in.bin"
    p.write_bytes(b"\x0a\x0b")
    cpu = Cpu()
    apply_input_to_cpu(cpu, str(p))
    assert list(cpu.input_queue) == [10, 11]


def test_apply_input_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Stdin:
        buffer = io.BytesIO(b"\x02\x03")

    monkeypatch.setattr(sys, "stdin", _Stdin())
    cpu = Cpu()
    apply_input_to_cpu(cpu, "-")
    assert list(cpu.input_queue) == [2, 3]


def test_main_with_input_file_runs(tmp_path) -> None:
    words = [
        pack_word(Opcode.IN, int(Port.DATA_IN)),
        pack_word(Opcode.HALT, 0),
    ]
    code = tmp_path / "code.bin"
    data = tmp_path / "data.bin"
    write_words_le(code, words)
    write_words_le(data, [])
    inp = tmp_path / "stdin.bin"
    inp.write_bytes(b"Z")

    exit_code = simulator_main(
        [str(code), str(data), "--input", str(inp), "--max-ticks", "1000"],
    )
    assert exit_code == 0
