from __future__ import annotations

from ak_lab4.io_schedule import IrqScheduleEvent
from ak_lab4.isa import Opcode, pack_word
from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many


def test_in_usr_returns_eof() -> None:
    words = compile_forms(parse_many("(in)\n")).code
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=50_000)
    assert machine.halted
    assert machine.dm[STACK_BASE] == 0xFFFFFFFF


def test_in_isr_reads_schedule_byte() -> None:
    src = "(nop)\n(interrupt 0 (progn (out (in)) (drop)))\n"
    words = compile_forms(parse_many(src)).code
    sched = (IrqScheduleEvent(0, 0, 66),)
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)
    run_program(machine, max_ticks=50_000)
    assert machine.halted
    assert bytes(machine.out_bytes) == b"B"


def test_superscalar_fewer_ticks_than_scalar() -> None:
    im = [0] * 32
    im[0] = pack_word(Opcode.PUSH_IMM, 10)
    im[1] = pack_word(Opcode.PUSH_IMM, 1)
    im[2] = pack_word(Opcode.STORE, 0)
    im[3] = pack_word(Opcode.PUSH_IMM, 11)
    im[4] = pack_word(Opcode.PUSH_IMM, 2)
    im[5] = pack_word(Opcode.STORE, 0)
    im[6] = pack_word(Opcode.PUSH_IMM, 12)
    im[7] = pack_word(Opcode.PUSH_IMM, 3)
    im[8] = pack_word(Opcode.STORE, 0)
    im[9] = pack_word(Opcode.HALT, 0)
    dm0 = [0] * 65536
    dm1 = [0] * 65536
    scalar = Machine(im=im, dm=dm0, pc=0, sp=STACK_BASE, superscalar=False)
    superc = Machine(im=im, dm=dm1, pc=0, sp=STACK_BASE, superscalar=True)
    run_program(scalar, max_ticks=500)
    run_program(superc, max_ticks=500)
    assert superc.ticks < scalar.ticks
