"""Суперскаляр: двойная выдача NOP/PUSH_IMM при superscalar=True."""

from __future__ import annotations

from io import StringIO

import pytest

from ak_lab4.cpu import Cpu, run_program
from ak_lab4.isa import Opcode, pack_word
from ak_lab4.memory import STACK_BASE


def _word(op: Opcode, operand: int = 0) -> int:
    return pack_word(op, operand)


def test_superscalar_nop_nop_advances_pc_by_two() -> None:
    im = [0] * 16
    im[0] = _word(Opcode.NOP)
    im[1] = _word(Opcode.NOP)
    im[2] = _word(Opcode.HALT)
    dm = [0] * 16
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)
    run_program(cpu, max_ticks=100)
    assert cpu.halted
    assert cpu.pc == 3
    assert cpu.ticks == 2


def test_superscalar_push_pair_stack_order() -> None:
    im = [0] * 16
    im[0] = _word(Opcode.PUSH_IMM, 7)
    im[1] = _word(Opcode.PUSH_IMM, 5)
    im[2] = _word(Opcode.HALT)
    dm = [0] * 65536
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)
    run_program(cpu, max_ticks=100)
    assert cpu.halted
    assert cpu.sp == STACK_BASE + 2
    assert cpu.dm[STACK_BASE] == 7
    assert cpu.dm[STACK_BASE + 1] == 5


def test_scalar_still_one_insn_per_step() -> None:
    im = [0] * 16
    im[0] = _word(Opcode.NOP)
    im[1] = _word(Opcode.NOP)
    im[2] = _word(Opcode.HALT)
    dm = [0] * 16
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=False)
    run_program(cpu, max_ticks=100)
    assert cpu.halted
    assert cpu.pc == 3
    assert cpu.ticks == 3


def test_log_par_line_on_dual_issue() -> None:
    im = [0] * 16
    im[0] = _word(Opcode.NOP)
    im[1] = _word(Opcode.NOP)
    im[2] = _word(Opcode.HALT)
    dm = [0] * 16
    buf = StringIO()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)
    run_program(cpu, max_ticks=100, log=buf)
    lines = buf.getvalue().strip().splitlines()
    assert lines[0].startswith("0\tPAR\t")
    assert "\tPAR\t" in lines[0]


@pytest.mark.parametrize(
    ("op1", "expect_dual"),
    [
        (Opcode.NOP, True),
        (Opcode.PUSH_IMM, True),
        (Opcode.JMP, False),
    ],
)
def test_dual_blocked_by_control_on_second(op1: Opcode, expect_dual: bool) -> None:
    im = [0] * 16
    im[0] = _word(Opcode.NOP)
    im[1] = _word(op1, 0 if op1 != Opcode.JMP else 5)
    im[2] = _word(Opcode.HALT)
    if op1 == Opcode.JMP:
        im[5] = _word(Opcode.HALT)
    dm = [0] * 65536
    buf = StringIO()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)
    run_program(cpu, max_ticks=200, log=buf)
    lines = buf.getvalue().strip().splitlines()
    has_par = any("\tPAR\t" in ln for ln in lines)
    assert has_par == expect_dual
