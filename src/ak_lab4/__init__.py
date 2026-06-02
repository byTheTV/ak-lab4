"""Лабораторная: транслятор и симулятор CPU"""

from ak_lab4.cpu import Cpu, CpuFault, init_memory_from_segments, run_program, scalar_ticks_for_opcode

__version__ = "0.1.0"

__all__ = [
    "Cpu",
    "CpuFault",
    "init_memory_from_segments",
    "run_program",
    "scalar_ticks_for_opcode",
    "__version__",
]
