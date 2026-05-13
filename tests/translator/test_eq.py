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


def test_eq_equal_ints() -> None:
    cpu = _run("(eq 3 3)")
    assert cpu.dm[STACK_BASE] == 1


def test_eq_not_equal() -> None:
    cpu = _run("(eq 1 2)")
    assert cpu.dm[STACK_BASE] == 0


def test_equals_alias() -> None:
    cpu = _run("(= 5 5)")
    assert cpu.dm[STACK_BASE] == 1


def test_eq_in_if_predicate() -> None:
    cpu = _run("(if (eq 2 2) 9 8)")
    assert cpu.dm[STACK_BASE] == 9


def test_eq_bad_arity() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse("(eq 1)"))
