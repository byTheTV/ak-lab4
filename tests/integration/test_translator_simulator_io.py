"""исходник -> транслятор -> code/data -> симулятор с --input"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.loader import load_words_le
from ak_lab4.memory import STACK_BASE
from ak_lab4.simulator.__main__ import main as simulator_main
from ak_lab4.translator import compile_program, parse
from ak_lab4.translator.cli import main as translator_main


def test_in_port_roundtrip_via_cli(tmp_path: Path) -> None:
    """только (in): байт из --input на вершине стека"""
    src = tmp_path / "prog.lisp"
    src.write_text("(in)\n", encoding="utf-8")
    code = tmp_path / "code.bin"
    data = tmp_path / "data.bin"
    inp = tmp_path / "stdin.bin"
    inp.write_bytes(bytes([99]))

    assert translator_main([str(src), "-o", str(code), "--data-out", str(data)]) == 0
    assert load_words_le(code) == compile_program(parse("(in)")).code

    rc = simulator_main([str(code), str(data), "--input", str(inp), "--max-ticks", "100000"])
    assert rc == 0

    words = load_words_le(code)
    dwords = load_words_le(data)
    im, dm = init_memory_from_segments(words, dwords)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, input_queue=deque([99]))
    run_program(cpu, max_ticks=100000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 99
