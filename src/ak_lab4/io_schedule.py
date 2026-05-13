"""Расписание IRQ/trap по глобальному счётчику тактов симуляции"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ak_lab4.isa import NUM_IRQ_LINES


@dataclass(frozen=True)
class IrqScheduleEvent:
    """На такте tick значение на линии irq"""

    tick: int
    irq: int
    value: int  # 0…255


def _byte_from_json_value(v: object) -> int:
    if isinstance(v, str):
        return ord(v[0]) & 0xFF if v else 0
    if isinstance(v, bool):
        return int(v) & 0xFF
    if isinstance(v, int):
        return v & 0xFF
    if isinstance(v, float):
        return int(v) & 0xFF
    msg = f"schedule: в value жду str/int/float, не {type(v).__name__}"
    raise TypeError(msg)


def load_irq_schedule_json(path: Path) -> tuple[IrqScheduleEvent, ...]:
    """JSON-массив {tick, irq, value}; value — число или одна буква в строке"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = "schedule: нужен массив JSON"
        raise ValueError(msg)
    out: list[IrqScheduleEvent] = []
    for i, o in enumerate(raw):
        if not isinstance(o, dict):
            msg = f"schedule: элемент {i} не объект JSON"
            raise ValueError(msg)
        tick = int(o["tick"])
        irq = int(o["irq"])
        if irq < 0 or irq >= NUM_IRQ_LINES:
            msg = f"schedule: irq вне 0…{NUM_IRQ_LINES - 1}"
            raise ValueError(msg)
        value = _byte_from_json_value(o.get("value", 0))
        out.append(IrqScheduleEvent(tick=tick, irq=irq, value=value))
    out.sort(key=lambda e: e.tick)
    return tuple(out)
