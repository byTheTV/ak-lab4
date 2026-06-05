from __future__ import annotations

from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import compile_program


def _run(expr_src: str) -> Machine:
    words = compile_program(parse(expr_src)).code
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=100_000)
    assert machine.halted
    return machine


def test_if_nonzero_then_branch() -> None:
    machine = _run("(if 7 10 20)")
    assert machine.dm[STACK_BASE] == 10
