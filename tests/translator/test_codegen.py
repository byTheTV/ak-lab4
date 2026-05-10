from __future__ import annotations

import pytest

from ak_lab4.isa import Opcode, unpack_word
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import IMM24_MAX, CodegenError, compile_program


def _ops(words: list[int]) -> list[int]:
    return [unpack_word(w)[0] for w in words]


def test_compile_literal_halts() -> None:
    w = compile_program(parse("13")).code
    assert _ops(w) == [int(Opcode.PUSH_IMM), int(Opcode.HALT)]
    assert w[0] & 0xFFFFFF == 13


def test_compile_add_two() -> None:
    w = compile_program(parse("(+ 1 2)")).code
    assert _ops(w) == [
        int(Opcode.PUSH_IMM),
        int(Opcode.PUSH_IMM),
        int(Opcode.ADD),
        int(Opcode.HALT),
    ]


def test_compile_add_three() -> None:
    w = compile_program(parse("(+ 10 20 5)")).code
    assert _ops(w) == [
        int(Opcode.PUSH_IMM),
        int(Opcode.PUSH_IMM),
        int(Opcode.ADD),
        int(Opcode.PUSH_IMM),
        int(Opcode.ADD),
        int(Opcode.HALT),
    ]


def test_nested_add() -> None:
    w = compile_program(parse("(+ (+ 1 2) 3)")).code
    assert _ops(w).count(int(Opcode.ADD)) == 2


def test_compile_sub_mul_div_mod() -> None:
    assert _ops(compile_program(parse("(- 10 3)")).code)[:3] == [
        int(Opcode.PUSH_IMM),
        int(Opcode.PUSH_IMM),
        int(Opcode.SUB),
    ]
    assert _ops(compile_program(parse("(* 2 3)")).code)[:3][2] == int(Opcode.MUL)
    assert _ops(compile_program(parse("(/ 6 2)")).code)[:3][2] == int(Opcode.DIV)
    assert _ops(compile_program(parse("(mod 7 3)")).code)[:3][2] == int(Opcode.MOD)


def test_imm24_out_of_range() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse(str(IMM24_MAX + 1)))


def test_unknown_form() -> None:
    with pytest.raises(CodegenError):
        compile_program(parse("(foo 1)"))
