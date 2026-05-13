from __future__ import annotations

import pytest

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import CodegenError, compile_program


def _run(expr_src: str) -> Cpu:
    words = compile_program(parse(expr_src)).code
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=100_000)
    assert cpu.halted
    return cpu


def test_if_zero_else_branch() -> None:
    cpu = _run("(if 0 10 20)")
    assert cpu.dm[STACK_BASE] == 20


def test_if_nonzero_then_branch() -> None:
    cpu = _run("(if 7 10 20)")
    assert cpu.dm[STACK_BASE] == 10


def test_if_with_arith_predicate() -> None:
    cpu = _run("(if (+ 1 1) 30 40)")
    assert cpu.dm[STACK_BASE] == 30


def test_nested_if() -> None:
    cpu = _run("(if 0 (if 0 1 2) (if 1 3 4))")
    assert cpu.dm[STACK_BASE] == 3


def test_if_wrong_arity() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse("(if 1 2)"))
