"""Golden: parse -> compile -> run, сверка артефактов в golden/<case>/"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TextIO

from ak_lab4.loader import write_words_le
from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_ROOT = REPO_ROOT / "golden"

GOLDEN_SOURCE_NAME = "source.tv"
CODE_BIN = "code.bin"
DATA_BIN = "data.bin"
CODE_LISTING = "code.listing"
DATA_LISTING = "data.listing"
TRACE_LOG = "trace.log"
OUTPUT_FILE = "output.txt"
INPUT_FILE = "input.txt"

_MAX_TICKS: dict[str, int] = {"prob1": 65_000_000}


@dataclass(frozen=True)
class CompiledCase:
    code: list[int]
    data: list[int]


@dataclass(frozen=True)
class TraceProfile:
    """Профиль сжатия журнала для длинных прогонов."""

    head_ticks: int
    sample_interval: int
    tail_ticks: int


# prob1: ~56M тактов → полный журнал ~1.7 ГБ; храним head + срезы + tail.
TRACE_PROFILES: dict[str, TraceProfile] = {
    "prob1": TraceProfile(head_ticks=500, sample_interval=5_000_000, tail_ticks=300),
}


def golden_dir(case: str) -> Path:
    return GOLDEN_ROOT / case


def compile_case(case: str) -> CompiledCase:
    src = (golden_dir(case) / GOLDEN_SOURCE_NAME).read_text(encoding="utf-8")
    prog = compile_forms(parse_many(src))
    return CompiledCase(code=prog.code, data=prog.data)


def format_listing(words: list[int]) -> str:
    if not words:
        return ""
    return "\n".join(f"{i} - {w:08X}" for i, w in enumerate(words)) + "\n"


def _input_queue(case: str) -> deque[int]:
    inp_path = golden_dir(case) / INPUT_FILE
    return deque(inp_path.read_bytes()) if inp_path.is_file() else deque()


def _max_ticks(case: str) -> int:
    return _MAX_TICKS.get(case, 10_000_000)


def adapt_trace_log(full_log: str, case: str) -> str:
    """Полный журнал или репрезентативный срез для длинных алгоритмов."""
    profile = TRACE_PROFILES.get(case)
    if profile is None:
        return full_log if full_log.endswith("\n") else full_log + "\n"

    lines = full_log.splitlines()
    if not lines:
        return "\n"

    parsed: list[tuple[int, str]] = []
    max_tick = 0
    for line in lines:
        tick = int(line.split("\t", 1)[0])
        max_tick = max(max_tick, tick)
        parsed.append((tick, line))

    keep_ticks: set[int] = set(range(1, profile.head_ticks + 1))
    for tick in range(profile.sample_interval, max_tick, profile.sample_interval):
        keep_ticks.add(tick)
    tail_start = max(1, max_tick - profile.tail_ticks + 1)
    keep_ticks.update(range(tail_start, max_tick + 1))

    selected = [line for tick, line in parsed if tick in keep_ticks]
    return "\n".join(selected) + "\n"


def run_case(
    case: str,
    *,
    max_ticks: int | None = None,
    superscalar: bool = False,
    log: TextIO | None = None,
) -> Machine:
    compiled = compile_case(case)
    im, dm = init_memory_from_segments(compiled.code, compiled.data)
    machine = Machine(
        im=im,
        dm=dm,
        pc=0,
        sp=STACK_BASE,
        input_queue=_input_queue(case),
        superscalar=superscalar,
    )
    run_program(machine, max_ticks=max_ticks or _max_ticks(case), log=log)
    assert machine.halted
    return machine


def capture_trace(case: str, *, superscalar: bool = False) -> str:
    buf = StringIO()
    run_case(case, superscalar=superscalar, log=buf)
    return adapt_trace_log(buf.getvalue(), case)


def read_golden_output(case: str) -> bytes:
    return (golden_dir(case) / OUTPUT_FILE).read_bytes()


def read_golden_text(case: str, name: str) -> str:
    return (golden_dir(case) / name).read_text(encoding="utf-8")


def write_golden_artifacts(case: str, *, superscalar: bool = False) -> None:
    """Перегенерация эталонов в golden/<case>/ (для локальной разработки)."""
    base = golden_dir(case)
    base.mkdir(parents=True, exist_ok=True)
    compiled = compile_case(case)
    write_words_le(base / CODE_BIN, compiled.code)
    write_words_le(base / DATA_BIN, compiled.data)
    (base / CODE_LISTING).write_text(format_listing(compiled.code), encoding="utf-8")
    (base / DATA_LISTING).write_text(format_listing(compiled.data), encoding="utf-8")
    buf = StringIO()
    machine = run_case(case, superscalar=superscalar, log=buf)
    (base / OUTPUT_FILE).write_bytes(bytes(machine.out_bytes))
    (base / TRACE_LOG).write_text(adapt_trace_log(buf.getvalue(), case), encoding="utf-8")


def all_golden_cases() -> tuple[str, ...]:
    return tuple(
        sorted(
            case_dir.name
            for case_dir in GOLDEN_ROOT.iterdir()
            if case_dir.is_dir()
            and (case_dir / GOLDEN_SOURCE_NAME).is_file()
            and (case_dir / OUTPUT_FILE).is_file()
        )
    )
