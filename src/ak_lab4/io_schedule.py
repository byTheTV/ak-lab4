"""Расписание прерываний/ввода по глобальным тактам симуляции (trap в смысле ТЗ)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IrqScheduleEvent:
    """Событие: на суммарном такте ``tick`` приходит значение на линию ``irq``."""

    tick: int
    irq: int
    value: int  # байт 0…255


def _byte_from_json_value(v: object) -> int:
    if isinstance(v, str):
        return ord(v[0]) & 0xFF if v else 0
    if isinstance(v, bool):
        return int(v) & 0xFF
    if isinstance(v, int):
        return v & 0xFF
    if isinstance(v, float):
        return int(v) & 0xFF
    msg = f"Расписание: value ожидается str/int/float, получено {type(v).__name__}"
    raise TypeError(msg)


def load_irq_schedule_json(path: Path) -> tuple[IrqScheduleEvent, ...]:
    """JSON-массив объектов ``{\"tick\": int, \"irq\": int, \"value\": …}``.

    ``value`` — число 0…255 или строка из одного символа (берётся код байта).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = "Расписание: ожидается JSON-массив"
        raise ValueError(msg)
    out: list[IrqScheduleEvent] = []
    for i, o in enumerate(raw):
        if not isinstance(o, dict):
            msg = f"Расписание: элемент {i} не объект"
            raise ValueError(msg)
        tick = int(o["tick"])
        irq = int(o["irq"])
        value = _byte_from_json_value(o.get("value", 0))
        out.append(IrqScheduleEvent(tick=tick, irq=irq, value=value))
    out.sort(key=lambda e: e.tick)
    return tuple(out)
