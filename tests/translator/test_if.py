from __future__ import annotations

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import compile_program


def _run(expr_src: str) -> Cpu:
    words = compile_program(parse(expr_src)).code
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=100_000)
    assert cpu.halted
    return cpu


def test_if_nonzero_then_branch() -> None:
    cpu = _run("(if 7 10 20)")
    assert cpu.dm[STACK_BASE] == 10
