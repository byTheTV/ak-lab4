from __future__ import annotations

from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import compile_program


def test_setq_stores_and_returns_value() -> None:
    words = compile_program(parse("(setq n 100)")).code
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=50_000)
    assert machine.halted
    assert machine.dm[0] == 100
    assert machine.sp == STACK_BASE + 1
    assert machine.dm[STACK_BASE] == 100
