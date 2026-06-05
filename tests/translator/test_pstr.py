"""строковые литералы -> pstr в DM"""

from __future__ import annotations

from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_program, parse


def test_str_lit_allocates_pstr_in_data_and_pushes_base() -> None:
    prog = compile_program(parse('"Hi"'))
    assert prog.data == [2, ord("H"), ord("i")]
    im, dm = init_memory_from_segments(prog.code, prog.data)
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=50_000)
    assert machine.halted
    assert machine.dm[STACK_BASE] == 0
