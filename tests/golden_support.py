"""Golden: parse → compile → run, сверка с expected_output.txt"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_ROOT = REPO_ROOT / "golden"

GOLDEN_SOURCE_NAME = "source.tv"


def run_case(
    case: str,
    *,
    max_ticks: int = 10_000_000,
    superscalar: bool = False,
) -> Cpu:
    base = GOLDEN_ROOT / case
    src = (base / GOLDEN_SOURCE_NAME).read_text(encoding="utf-8")
    forms = parse_many(src)
    prog = compile_forms(forms)
    im, dm = init_memory_from_segments(prog.code, prog.data)
    inp_path = base / "input.txt"
    queue: deque[int] = deque(inp_path.read_bytes()) if inp_path.is_file() else deque()
    cpu = Cpu(
        im=im,
        dm=dm,
        pc=0,
        sp=STACK_BASE,
        input_queue=queue,
        superscalar=superscalar,
    )
    run_program(cpu, max_ticks=max_ticks)
    assert cpu.halted
    return cpu


def read_expected_output(case: str) -> bytes:
    return (GOLDEN_ROOT / case / "expected_output.txt").read_bytes()
