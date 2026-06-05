from __future__ import annotations

import pytest

from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import CodegenError, compile_forms, compile_program, parse


def _run(src: str) -> Machine:
    words = compile_program(parse(src)).code
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=200_000)
    assert machine.halted
    return machine


def test_progn_setq_then_use() -> None:
    machine = _run("(progn (setq n 4) (+ n 1))")
    assert machine.dm[0] == 4
    assert machine.dm[STACK_BASE] == 5


def test_compile_forms_empty_raises() -> None:
    with pytest.raises(CodegenError):
        compile_forms(())
