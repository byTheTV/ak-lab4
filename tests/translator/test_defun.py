from __future__ import annotations

from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many


def _run_module(src: str) -> Machine:
    words = compile_forms(parse_many(src)).code
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=500_000)
    assert machine.halted
    return machine


def test_defun_zero_args_literal() -> None:
    machine = _run_module("(defun five () 5)(five)")
    assert machine.dm[STACK_BASE] == 5


def test_defun_one_param() -> None:
    machine = _run_module("(defun inc (x) (+ x 1))(inc 5)")
    assert machine.dm[STACK_BASE] == 6


def test_defun_forward_call() -> None:
    """вызов функции, которая объявлена ниже по тексту"""
    machine = _run_module("(defun a () (b))(defun b () 1)(a)")
    assert machine.dm[STACK_BASE] == 1
