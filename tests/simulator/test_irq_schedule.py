from __future__ import annotations

import json

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.io_schedule import IrqScheduleEvent, load_irq_schedule_json
from ak_lab4.isa import Opcode, pack_word
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many


def test_load_schedule_json(tmp_path) -> None:
    p = tmp_path / "s.json"
    p.write_text(
        json.dumps([{"tick": 0, "irq": 0, "value": "A"}, {"tick": 10, "irq": 1, "value": 7}]),
        encoding="utf-8",
    )
    ev = load_irq_schedule_json(p)
    assert ev == (
        IrqScheduleEvent(0, 0, ord("A")),
        IrqScheduleEvent(10, 1, 7),
    )


def test_irq_schedule_delivers_to_handler_via_in() -> None:
    """trap по расписанию; первый IN в ISR берёт байт с линии, не из stdin"""
    words = compile_forms(
        parse_many(
            "(nop)\n(interrupt 0 (in))\n",
        ),
    ).code
    sched = (IrqScheduleEvent(0, 0, 66),)
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.irq_latches[0] == 66


def test_irq_tick_zero_delivers_before_first_issue() -> None:
    """Событие tick=0 доставляется в начале первого шага."""
    im, dm = init_memory_from_segments([], [])
    im[0] = pack_word(Opcode.JMP, 10)  # main entry
    im[1] = pack_word(Opcode.JMP, 20)  # IRQ0 vector
    im[10] = pack_word(Opcode.HALT, 0)
    im[20] = pack_word(Opcode.RET, 0)
    sched = (IrqScheduleEvent(0, 0, ord("A")),)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)

    cpu.step()

    assert cpu.ticks == 1
    assert cpu.pc == 20
    assert cpu.interrupt_depth == 1


def test_irq_tick_one_not_delivered_on_first_step() -> None:
    """Событие tick=1 не должно срабатывать на первом шаге."""
    im, dm = init_memory_from_segments([], [])
    im[0] = pack_word(Opcode.JMP, 10)  # main entry
    im[1] = pack_word(Opcode.JMP, 20)  # IRQ0 vector
    im[10] = pack_word(Opcode.HALT, 0)
    im[20] = pack_word(Opcode.RET, 0)
    sched = (IrqScheduleEvent(1, 0, ord("A")),)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)

    cpu.step()
    assert cpu.pc == 10
    assert cpu.interrupt_depth == 0

    cpu.step()
    assert cpu.pc == 20
    assert cpu.interrupt_depth == 1
