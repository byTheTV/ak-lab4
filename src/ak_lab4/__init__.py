"""Лабораторная: транслятор и симулятор процессора"""

from ak_lab4.machine import (
    ControlUnit,
    DataPath,
    Machine,
    MachineFault,
    init_memory_from_segments,
    run_program,
    scalar_ticks_for_opcode,
)

__version__ = "0.1.0"

__all__ = [
    "ControlUnit",
    "DataPath",
    "Machine",
    "MachineFault",
    "init_memory_from_segments",
    "run_program",
    "scalar_ticks_for_opcode",
    "__version__",
]
