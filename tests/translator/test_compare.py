from __future__ import annotations

import pytest

from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import CodegenError, compile_program


def _run(src: str) -> Machine:
    words = compile_program(parse(src)).code
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=100_000)
    assert machine.halted
    return machine


def test_lt_true() -> None:
    machine = _run("(< 1 5)")
    assert machine.dm[STACK_BASE] == 1


def test_compare_bad_arity() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse("(< 1)"))
