from __future__ import annotations

import pytest

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import CodegenError, compile_program


def _run(src: str) -> Cpu:
    words = compile_program(parse(src)).code
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=100_000)
    assert cpu.halted
    return cpu


def test_lt_true() -> None:
    cpu = _run("(< 1 5)")
    assert cpu.dm[STACK_BASE] == 1


def test_compare_bad_arity() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse("(< 1)"))
