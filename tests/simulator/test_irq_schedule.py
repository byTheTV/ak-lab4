from __future__ import annotations

import json

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.io_schedule import IrqScheduleEvent, load_irq_schedule_json
from ak_lab4.isa import Opcode, Port, pack_word
from ak_lab4.memory import STACK_BASE


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


def test_schedule_injects_byte_before_in_instruction(tmp_path) -> None:
    """На такте 0 байт попадает в очередь до первого IN."""
    words = [
        pack_word(Opcode.IN, int(Port.DATA_IN)),
        pack_word(Opcode.HALT, 0),
    ]
    im, dm = init_memory_from_segments(words, [])
    sched = (IrqScheduleEvent(0, 0, 66),)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 66
    assert cpu.irq_latches[0] == 66


def test_schedule_tick_after_some_instructions(tmp_path) -> None:
    """Событие на более позднем такте встаёт в очередь позже."""
    words = [
        pack_word(Opcode.NOP, 0),
        pack_word(Opcode.IN, int(Port.DATA_IN)),
        pack_word(Opcode.HALT, 0),
    ]
    # NOP = 1 такт; после NOP ticks=1; перед IN нужно событие с tick<=1
    sched = (IrqScheduleEvent(1, 0, 99),)
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE, irq_schedule=sched)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 99
