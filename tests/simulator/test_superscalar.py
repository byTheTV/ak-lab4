"""Суперскаляр: двойная выдача NOP/PUSH_IMM при superscalar=True."""

from __future__ import annotations

from io import StringIO

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
    assert "\tPAR\t" in lines[0]


def test_dual_blocked_by_control_on_second() -> None:
    op1 = Opcode.JMP
    im = [0] * 16
    im[0] = _word(Opcode.NOP)
    im[1] = _word(op1, 5)
    im[2] = _word(Opcode.HALT)
    im[5] = _word(Opcode.HALT)
    dm = [0] * 65536
    buf = StringIO()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)
    run_program(cpu, max_ticks=200, log=buf)
    lines = buf.getvalue().strip().splitlines()
    has_par = any("\tPAR\t" in ln for ln in lines)
    assert has_par is False


def test_deferred_store_visible_only_after_flush_on_halt() -> None:
    im = [0] * 16
    addr = 9
    value = 77
    im[0] = _word(Opcode.PUSH_IMM, addr)
    im[1] = _word(Opcode.PUSH_IMM, value)
    im[2] = _word(Opcode.STORE)
    im[3] = _word(Opcode.HALT)
    dm = [0] * 65536
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)

    cpu.step()  # push addr + push value
    while cpu.pc < 3:
        cpu.step()  # stall/issue до момента после STORE
    assert cpu.dm[addr] == 0
    assert cpu.shadow_stores == [(addr, value)]

    run_program(cpu, max_ticks=200)  # halt -> flush
    assert cpu.halted
    assert cpu.dm[addr] == value
    assert cpu.shadow_stores == []


def test_irq_delivery_flushes_shadow_before_isr() -> None:
    im = [0] * 64
    im[0] = _word(Opcode.JMP, 10)
    im[1] = _word(Opcode.JMP, 20)  # vector IRQ0
    im[10] = _word(Opcode.PUSH_IMM, 15)
    im[11] = _word(Opcode.PUSH_IMM, 55)
    im[12] = _word(Opcode.STORE)
    im[13] = _word(Opcode.HALT)
    im[20] = _word(Opcode.RET)
    dm = [0] * 65536
    buf = StringIO()
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, superscalar=True)

    cpu.step(log=buf)  # jmp 10
    cpu.step(log=buf)  # push pair
    while cpu.pc < 13:
        cpu.step(log=buf)  # stall/issue до STORE
    assert cpu.shadow_stores == [(15, 55)]
    cpu.irq_pending[0] = True
    cpu.irq_line_value[0] = 65
    cpu.step(log=buf)  # irq delivery + flush shadow

    assert cpu.pc == 20
    assert cpu.interrupt_depth == 1
    assert cpu.dm[15] == 55
    assert cpu.shadow_stores == []
    assert any("\tPAR_FLUSH\tirq\t" in ln for ln in buf.getvalue().splitlines())


def test_superscalar_tick_gain_on_shadow_workload() -> None:
    im = [0] * 32
    im[0] = _word(Opcode.PUSH_IMM, 10)
    im[1] = _word(Opcode.PUSH_IMM, 1)
    im[2] = _word(Opcode.STORE)
    im[3] = _word(Opcode.PUSH_IMM, 11)
    im[4] = _word(Opcode.PUSH_IMM, 2)
    im[5] = _word(Opcode.STORE)
    im[6] = _word(Opcode.PUSH_IMM, 12)
    im[7] = _word(Opcode.PUSH_IMM, 3)
    im[8] = _word(Opcode.STORE)
    im[9] = _word(Opcode.HALT)
    dm0 = [0] * 65536
    dm1 = [0] * 65536
    scalar = Cpu(im=im, dm=dm0, pc=0, sp=STACK_BASE, superscalar=False)
    superc = Cpu(im=im, dm=dm1, pc=0, sp=STACK_BASE, superscalar=True)

    run_program(scalar, max_ticks=500)
    run_program(superc, max_ticks=500)
    assert superc.ticks < scalar.ticks
