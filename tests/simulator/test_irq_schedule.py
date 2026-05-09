from __future__ import annotations

import json

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.io_schedule import IrqScheduleEvent, load_irq_schedule_json
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
    """Расписание выставляет запрос; данные читает обработчик (interrupt), не «магическая» очередь stdin."""
    words = compile_forms(
        parse_many(
            "(nop)\n(interrupt 0 (in))\n",
        ),
    )
    sched = (IrqScheduleEvent(0, 0, 66),)
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 66
    assert cpu.irq_latches[0] == 66


def test_irq_tick_after_nop_before_halt() -> None:
    """Событие на такте 3 — после JMP (2 т.) и NOP (1 т.), обработчик до встроенного HALT."""
    words = compile_forms(
        parse_many(
            "(nop)\n(interrupt 0 (in))\n",
        ),
    )
    sched = (IrqScheduleEvent(3, 0, 99),)
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 99


def test_log_prefix_isr(tmp_path) -> None:
    """Журнал помечает режим USR/ISR (см. ТЗ: видно, в прерывании выполнение или нет)."""
    words = compile_forms(parse_many("(nop)\n(interrupt 0 (nop))\n"))
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=(IrqScheduleEvent(1, 0, 0),))
    log = tmp_path / "x.log"
    with log.open("w", encoding="utf-8") as f:
        run_program(cpu, max_ticks=10000, log=f)
    text = log.read_text(encoding="utf-8")
    assert "\tISR\n" in text
    assert "\tUSR\n" in text
