from __future__ import annotations

import pytest

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import CodegenError, compile_forms, compile_program, parse, parse_many


def _run(src: str) -> Cpu:
    words = compile_program(parse(src)).code
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=200_000)
    assert cpu.halted
    return cpu


def test_progn_setq_then_use() -> None:
    cpu = _run("(progn (setq n 4) (+ n 1))")
    assert cpu.dm[0] == 4
    assert cpu.dm[STACK_BASE] == 5


def test_progn_three_drops() -> None:
    cpu = _run("(progn 1 2 3)")
    assert cpu.dm[STACK_BASE] == 3


def test_compile_forms_one_same_as_compile_program() -> None:
    assert compile_forms(parse_many("(+ 1 2)")).code == compile_program(parse("(+ 1 2)")).code


def test_compile_forms_two_matches_progn() -> None:
    src = "(setq a 1)(+ a 2)"
    w = compile_forms(parse_many(src)).code
    assert w == compile_program(parse("(progn (setq a 1) (+ a 2))")).code


def test_compile_forms_empty_raises() -> None:
    with pytest.raises(CodegenError):
        compile_forms(())
