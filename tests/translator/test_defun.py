from __future__ import annotations

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many


def _run_module(src: str) -> Cpu:
    words = compile_forms(parse_many(src)).code
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=500_000)
    assert cpu.halted
    return cpu


def test_defun_zero_args_literal() -> None:
    cpu = _run_module("(defun five () 5)(five)")
    assert cpu.dm[STACK_BASE] == 5


def test_defun_calls_defun_below() -> None:
    src = "(defun a () 1)(defun b () (+ (a) 2))(b)"
    cpu = _run_module(src)
    assert cpu.dm[STACK_BASE] == 3


def test_swap_ret_preserves_result_under_return_pc() -> None:
    """после CALL на стеке ret; значение функции — SWAP и RET не затирают"""
    cpu = _run_module("(defun x () (+ 9 9))(x)")
    assert cpu.dm[STACK_BASE] == 18


def test_defun_one_param() -> None:
    cpu = _run_module("(defun inc (x) (+ x 1))(inc 5)")
    assert cpu.dm[STACK_BASE] == 6


def test_defun_two_params() -> None:
    cpu = _run_module("(defun add (a b) (+ a b))(add 10 20)")
    assert cpu.dm[STACK_BASE] == 30


def test_defun_forward_call() -> None:
    """вызов функции, которая объявлена ниже по тексту"""
    cpu = _run_module("(defun a () (b))(defun b () 1)(a)")
    assert cpu.dm[STACK_BASE] == 1


def test_defun_forward_call_with_param() -> None:
    cpu = _run_module("(defun f (x) (g x))(defun g (y) (+ y 1))(f 4)")
    assert cpu.dm[STACK_BASE] == 5


def test_defun_body_implicit_progn() -> None:
    """несколько форм в теле — как progn: эффекты по порядку, значение у последней"""
    src = "(defun f (x) (setq acc (+ acc x)) (+ acc 10))(setq acc 0)(f 3)"
    cpu = _run_module(src)
    assert cpu.dm[STACK_BASE] == 13
