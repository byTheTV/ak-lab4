"""Scalar pipeline: FETCH + PHASE по опкодам (без superscalar)."""

from __future__ import annotations

from io import StringIO

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.isa import Opcode, pack_word
from ak_lab4.memory import STACK_BASE


def _w(op: Opcode, operand: int = 0) -> int:
    return pack_word(op, operand)


def test_scalar_push_imm_uses_fetch_and_phase() -> None:
    code = [_w(Opcode.PUSH_IMM, 42), _w(Opcode.HALT)]
    im, dm = init_memory_from_segments(code, [])
    buf = StringIO()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=False)
    cpu.step(log=buf)
    cpu.step(log=buf)
    lines = buf.getvalue().splitlines()
    assert any("\tFETCH\t" in ln for ln in lines)
    assert any("\tPHASE\t" in ln and "\twriteback\t" in ln for ln in lines)
    assert cpu.dm[STACK_BASE] == 42


def test_scalar_jz_taken_skips_fallthrough() -> None:
    """JZ: execute + branch + writeback после FETCH."""
    target = 4
    code = [
        _w(Opcode.PUSH_IMM, 0),
        _w(Opcode.JZ, target),
        _w(Opcode.PUSH_IMM, 1),
        _w(Opcode.HALT),
        _w(Opcode.PUSH_IMM, 99),
        _w(Opcode.HALT),
    ]
    im, dm = init_memory_from_segments(code, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=100)
    assert cpu.halted
    assert cpu.sp == STACK_BASE + 1
    assert cpu.dm[STACK_BASE] == 99


def test_scalar_mul_phases() -> None:
    code = [
        _w(Opcode.PUSH_IMM, 6),
        _w(Opcode.PUSH_IMM, 7),
        _w(Opcode.MUL),
        _w(Opcode.HALT),
    ]
    im, dm = init_memory_from_segments(code, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=100)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 42
