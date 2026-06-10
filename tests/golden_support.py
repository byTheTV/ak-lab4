from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, TextIO

import yaml

from ak_lab4.io_schedule import IrqScheduleEvent
from ak_lab4.isa import Opcode, unpack_word
from ak_lab4.machine import Machine, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import compile_forms, parse_many

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_ROOT = REPO_ROOT / "golden"

_DEFAULT_MAX_TICKS = 10_000_000
_MAX_TICKS: dict[str, int] = {"prob1": 65_000_000}

_LOG_PROFILES: dict[str, tuple[int, int, int]] = {
    "prob1": (500, 5_000_000, 300),
}

_LOG_FULL_LIMIT = 80
_LOG_HEAD = 18
_LOG_TAIL = 14
_LOG_IRQ_CTX = 5


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.nodes.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _str_representer, Dumper=yaml.SafeDumper)


@dataclass(frozen=True)
class GoldenRun:
    output: bytes
    log_excerpt: list[str]
    code_listing: str
    data_listing: str


def golden_yml_paths() -> tuple[Path, ...]:
    return tuple(sorted(GOLDEN_ROOT.glob("*.yml")))


def load_golden_yml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: ожидается mapping"
        raise TypeError(msg)
    return data


def format_output(data: bytes) -> str:
    if not data:
        return ""
    if all(x in (9, 10, 13) or 32 <= x < 127 for x in data):
        return data.decode("ascii")
    out: list[str] = []
    for byte in data:
        if byte in (9, 10, 13) or 32 <= byte < 127:
            out.append(chr(byte))
        else:
            out.append(f"\\x{byte:02x}")
    return "".join(out)


def parse_output(text: str) -> bytes:
    if "\\x" not in text:
        return text.encode("utf-8")
    out = bytearray()
    i = 0
    while i < len(text):
        if text.startswith("\\n", i):
            out.append(10)
            i += 2
            continue
        if text.startswith("\\r", i):
            out.append(13)
            i += 2
            continue
        if text.startswith("\\t", i):
            out.append(9)
            i += 2
            continue
        if text.startswith("\\x", i) and i + 4 <= len(text):
            out.append(int(text[i + 2 : i + 4], 16))
            i += 4
            continue
        out.append(ord(text[i]))
        i += 1
    return bytes(out)


def schedule_to_input(schedule: tuple[IrqScheduleEvent, ...]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ev in schedule:
        item: dict[str, Any] = {"tick": ev.tick, "irq": ev.irq}
        if ev.eof:
            item["eof"] = True
        else:
            value = ev.value & 0xFF
            if 32 <= value < 127:
                item["byte"] = chr(value)
            else:
                item["byte"] = value
        items.append(item)
    return items


def parse_input(raw: object) -> tuple[IrqScheduleEvent, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        msg = "input: ожидается список"
        raise TypeError(msg)
    out: list[IrqScheduleEvent] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            msg = f"input[{i}]: ожидается объект"
            raise TypeError(msg)
        tick = int(item["tick"])
        irq = int(item["irq"])
        eof = bool(item.get("eof", False))
        if eof:
            out.append(IrqScheduleEvent(tick=tick, irq=irq, eof=True))
            continue
        value = item.get("byte", item.get("value", 0))
        byte = (ord(value[0]) if value else 0) if isinstance(value, str) else int(value) & 0xFF
        out.append(IrqScheduleEvent(tick=tick, irq=irq, value=byte))
    out.sort(key=lambda e: e.tick)
    return tuple(out)


def format_listing(words: list[int]) -> str:
    if not words:
        return ""
    return "\n".join(f"{i} - {w:08X}" for i, w in enumerate(words)) + "\n"


def words_from_listing(text: str) -> list[int]:
    words: list[int] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        _, hexpart = line.split(" - ", 1)
        words.append(int(hexpart.strip(), 16))
    return words


def _select_log_lines(full_log: str, case: str) -> list[str]:
    lines = [ln for ln in full_log.splitlines() if ln.strip()]
    if not lines:
        return []
    if len(lines) <= _LOG_FULL_LIMIT:
        return lines

    profile = _LOG_PROFILES.get(case)
    if profile is not None:
        head_ticks, sample_interval, tail_ticks = profile
        parsed: list[tuple[int, str]] = []
        max_tick = 0
        for line in lines:
            tick = int(line.split("\t", 1)[0])
            max_tick = max(max_tick, tick)
            parsed.append((tick, line))
        keep_ticks: set[int] = set(range(1, head_ticks + 1))
        for tick in range(sample_interval, max_tick, sample_interval):
            keep_ticks.add(tick)
        tail_start = max(1, max_tick - tail_ticks + 1)
        keep_ticks.update(range(tail_start, max_tick + 1))
        return [line for tick, line in parsed if tick in keep_ticks]

    keep: set[int] = set(range(min(_LOG_HEAD, len(lines))))
    keep.update(range(max(0, len(lines) - _LOG_TAIL), len(lines)))
    for i, line in enumerate(lines):
        if "\tIRQ_TRAP\t" in line:
            lo = max(0, i - 1)
            hi = min(len(lines), i + _LOG_IRQ_CTX)
            keep.update(range(lo, hi))
        if "\tPAR\t" in line or "\tPAR_FLUSH\t" in line:
            keep.add(i)
        if "\tFETCH\t" in line and "\tHALT\t" not in line:
            parts = line.split("\t")
            if len(parts) >= 4:
                op, _ = unpack_word(int(parts[3], 16))
                if op == int(Opcode.HALT):
                    keep.update(range(max(0, i - 2), min(len(lines), i + 3)))
    return [lines[i] for i in sorted(keep)]


def build_log_excerpt(full_log: str, case: str) -> list[str]:
    return _select_log_lines(full_log, case)


def run_source(
    source: str,
    *,
    schedule: tuple[IrqScheduleEvent, ...] = (),
    case: str = "",
    max_ticks: int | None = None,
    superscalar: bool = False,
    log: TextIO | None = None,
    code_listing: str | None = None,
    data_listing: str | None = None,
) -> tuple[Machine, list[int], list[int]]:
    if code_listing is not None and data_listing is not None:
        code = words_from_listing(code_listing)
        data = words_from_listing(data_listing)
    else:
        compiled = compile_forms(parse_many(source))
        code, data = compiled.code, compiled.data
    im, dm = init_memory_from_segments(code, data)
    limit = max_ticks if max_ticks is not None else _MAX_TICKS.get(case, _DEFAULT_MAX_TICKS)
    machine = Machine(
        im=im,
        dm=dm,
        pc=0,
        sp=STACK_BASE,
        irq_schedule=schedule,
        superscalar=superscalar,
    )
    run_program(machine, max_ticks=limit, log=log)
    if not machine.halted:
        msg = f"HALT не достигнут ({case})"
        raise AssertionError(msg)
    return machine, code, data


def capture_run(
    source: str,
    *,
    schedule: tuple[IrqScheduleEvent, ...] = (),
    case: str = "",
    superscalar: bool = False,
    code_listing: str | None = None,
    data_listing: str | None = None,
    max_ticks: int | None = None,
) -> GoldenRun:
    buf = StringIO()
    machine, code, data = run_source(
        source,
        schedule=schedule,
        case=case,
        superscalar=superscalar,
        log=buf,
        code_listing=code_listing,
        data_listing=data_listing,
        max_ticks=max_ticks,
    )
    return GoldenRun(
        output=bytes(machine.out_bytes),
        log_excerpt=build_log_excerpt(buf.getvalue(), case),
        code_listing=format_listing(code),
        data_listing=format_listing(data),
    )


def build_golden_document(
    source: str,
    *,
    schedule: tuple[IrqScheduleEvent, ...] = (),
    case: str = "",
    superscalar: bool = False,
) -> dict[str, Any]:
    limit = _MAX_TICKS.get(case, _DEFAULT_MAX_TICKS)
    run = capture_run(
        source,
        schedule=schedule,
        case=case,
        superscalar=superscalar,
        max_ticks=limit,
    )
    doc: dict[str, Any] = {
        "name": case,
        "source": source if source.endswith("\n") else source + "\n",
        "input": schedule_to_input(schedule),
        "max_ticks": limit,
        "fail_on_max_ticks": True,
        "output": format_output(run.output),
        "code_listing": run.code_listing,
        "data_listing": run.data_listing,
        "log_excerpt": run.log_excerpt,
    }
    return doc


def write_golden_yml(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            doc,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def run_from_yml(path: Path, *, superscalar: bool = False) -> GoldenRun:
    doc = load_golden_yml(path)
    source = str(doc["source"])
    schedule = parse_input(doc.get("input", doc.get("schedule")))
    case = str(doc.get("name", path.stem))
    max_ticks = int(doc["max_ticks"]) if "max_ticks" in doc else None
    listing_code = str(doc["code_listing"]) if case == "prob1" else None
    listing_data = str(doc["data_listing"]) if case == "prob1" else None
    return capture_run(
        source,
        schedule=schedule,
        case=case,
        superscalar=superscalar,
        code_listing=listing_code,
        data_listing=listing_data,
        max_ticks=max_ticks,
    )
