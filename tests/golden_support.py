"""Общая логика golden: та же цепочка, что CLI, но без subprocess — сравнение с эталоном по out_bytes."""

from __future__ import annotations

from pathlib import Path

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_ROOT = REPO_ROOT / "golden"


def run_case(case: str, *, max_ticks: int = 10_000_000) -> Cpu:
    """Скомпилировать ``golden/<case>/source.lisp``, исполнить до HALT."""
    base = GOLDEN_ROOT / case
    src = (base / "source.lisp").read_text(encoding="utf-8")
    forms = parse_many(src)
    words = compile_forms(forms)
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=max_ticks)
    assert cpu.halted
    return cpu


def read_expected_output(case: str) -> bytes:
    """Сырые байты эталона вывода (DATA_OUT)."""
    return (GOLDEN_ROOT / case / "expected_output.txt").read_bytes()
