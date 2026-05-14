from __future__ import annotations

from collections import deque

import pytest

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import CodegenError, compile_program


def _run(src: str, *, input_bytes: list[int] | None = None) -> Cpu:
    words = compile_program(parse(src)).code
    im, dm = init_memory_from_segments(words, [])
    q = deque(input_bytes) if input_bytes is not None else deque()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, input_queue=q)
    run_program(cpu, max_ticks=100_000)
    assert cpu.halted
    return cpu


def test_in_reads_data_in_port() -> None:
    cpu = _run("(in)", input_bytes=[7])
    assert cpu.dm[STACK_BASE] == 7


def test_out_writes_low_byte_and_returns_value() -> None:
    cpu = _run("(out (+ 10 32))")
    assert cpu.out_bytes == [42]
    assert cpu.dm[STACK_BASE] == 42


def test_in_requires_zero_args() -> None:
    with pytest.raises(CodegenError, match="in без аргументов"):
        compile_program(parse("(in 0)"))
