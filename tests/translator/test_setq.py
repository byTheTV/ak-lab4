from __future__ import annotations

import pytest

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import CodegenError, compile_program


def test_setq_stores_and_returns_value() -> None:
    words = compile_program(parse("(setq n 100)"))
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[0] == 100
    assert cpu.sp == STACK_BASE + 1
    assert cpu.dm[STACK_BASE] == 100


def test_plus_with_inner_setq() -> None:
    words = compile_program(parse("(+ (setq x 5) 3)"))
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[0] == 5
    assert cpu.dm[STACK_BASE] == 8


def test_nested_setq_assignment_value() -> None:
    words = compile_program(parse("(setq a (setq b 2))"))
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[0] == 2
    assert cpu.dm[1] == 2


def test_unknown_global_symbol() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse("(+ x 1)"))
