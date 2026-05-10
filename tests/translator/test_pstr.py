"""строковые литералы → pstr в DM"""

from __future__ import annotations

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_program, parse


def test_str_lit_allocates_pstr_in_data_and_pushes_base() -> None:
    prog = compile_program(parse('"Hi"'))
    assert prog.data == [2, ord("H"), ord("i")]
    im, dm = init_memory_from_segments(prog.code, prog.data)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 0


def test_duplicate_string_literals_share_one_allocation() -> None:
    prog = compile_program(parse('(eq "x" "x")'))
    assert prog.data == [1, ord("x")]
    im, dm = init_memory_from_segments(prog.code, prog.data)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 1


def test_string_then_var_slots_after_pstr() -> None:
    prog = compile_program(parse('(progn (setq n 1) "ab")'))
    assert prog.data == [2, ord("a"), ord("b")]
    im, dm = init_memory_from_segments(prog.code, prog.data)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[3] == 1
