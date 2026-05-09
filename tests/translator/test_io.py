from __future__ import annotations

from collections import deque

import pytest

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.isa import Opcode, Port, unpack_word
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse, parse_many
from ak_lab4.translator.codegen import CodegenError, compile_program


def _run(src: str, *, input_bytes: list[int] | None = None) -> Cpu:
    words = compile_program(parse(src))
    im, dm = init_memory_from_segments(words, [])
    q = deque(input_bytes) if input_bytes is not None else deque()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, input_queue=q)
    run_program(cpu, max_ticks=100_000)
    assert cpu.halted
    return cpu


def test_in_reads_data_in_port() -> None:
    cpu = _run("(in)", input_bytes=[7])
    assert cpu.dm[STACK_BASE] == 7


def test_in_eof_minus_one() -> None:
    cpu = _run("(in)")
    assert cpu.dm[STACK_BASE] == 0xFFFFFFFF


def test_out_writes_low_byte_and_returns_value() -> None:
    cpu = _run("(out (+ 10 32))")
    assert cpu.out_bytes == [42]
    assert cpu.dm[STACK_BASE] == 42


def test_out_in_progn_side_effect() -> None:
    """Последняя форма progn задаёт результат на стеке."""
    src = "(progn (out 1) (+ 2 3))"
    words = compile_forms(parse_many(src))
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=100_000)
    assert cpu.halted
    assert cpu.out_bytes == [1]
    assert cpu.dm[STACK_BASE] == 5


def test_in_requires_zero_args() -> None:
    with pytest.raises(CodegenError, match="in не принимает"):
        compile_program(parse("(in 0)"))


def test_out_requires_one_arg() -> None:
    with pytest.raises(CodegenError, match="out ожидает"):
        compile_program(parse("(out)"))


def test_in_generates_in_data_port() -> None:
    w = compile_program(parse("(in)"))
    op, imm = unpack_word(w[0])
    assert op == int(Opcode.IN)
    assert imm == int(Port.DATA_IN)


def test_out_generates_dup_and_out() -> None:
    w = compile_program(parse("(out 9)"))
    assert unpack_word(w[0])[0] == int(Opcode.PUSH_IMM)
    assert unpack_word(w[1])[0] == int(Opcode.DUP)
    op, imm = unpack_word(w[2])
    assert op == int(Opcode.OUT)
    assert imm == int(Port.DATA_OUT)
