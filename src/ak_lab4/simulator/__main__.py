"""Запуск: python -m ak_lab4.simulator"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ak_lab4.cpu import Cpu, CpuFault, init_memory_from_segments, run_program
from ak_lab4.io_schedule import IrqScheduleEvent, load_irq_schedule_json
from ak_lab4.loader import load_words_le
from ak_lab4.memory import STACK_BASE


def apply_input_to_cpu(cpu: Cpu, spec: str) -> None:
    raw = sys.stdin.buffer.read() if spec == "-" else Path(spec).read_bytes()
    cpu.input_queue.extend(raw)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Гарвард: пара code.bin + data.bin")
    p.add_argument("code", type=Path, help="бинарник кода (IM)")
    p.add_argument("data", type=Path, help="бинарник данных (DM)")
    p.add_argument("--log", type=Path, default=None, help="куда писать журнал исполнения")
    p.add_argument(
        "--max-ticks",
        type=int,
        default=10_000_000,
        metavar="N",
        help="стоп после стольких тактов (по умолчанию 10^7)",
    )
    p.add_argument(
        "--input",
        metavar="PATH|-",
        default=None,
        help="байты в DATA_IN; «-» — весь stdin",
    )
    p.add_argument(
        "--schedule",
        type=Path,
        default=None,
        metavar="PATH",
        help="JSON событий trap: tick, irq, value",
    )
    p.add_argument(
        "--superscalar",
        action="store_true",
        help="двойная выдача + AC_SHADOW (deferred store, DLE, parallel flush)",
    )
    args = p.parse_args(argv)

    try:
        code_words = load_words_le(args.code)
        data_words = load_words_le(args.data)
    except OSError as e:
        print(e, file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    im, dm = init_memory_from_segments(code_words, data_words)

    irq_sched: tuple[IrqScheduleEvent, ...] = ()
    if args.schedule is not None:
        try:
            irq_sched = load_irq_schedule_json(args.schedule)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            print(f"--schedule: {e}", file=sys.stderr)
            return 2

    cpu = Cpu(
        im=im,
        dm=dm,
        pc=0,
        sp=STACK_BASE,
        irq_schedule=irq_sched,
        superscalar=args.superscalar,
    )

    if args.input is not None:
        try:
            apply_input_to_cpu(cpu, args.input)
        except OSError as e:
            print(e, file=sys.stderr)
            return 2

    log_file = None
    try:
        if args.log is not None:
            log_file = args.log.open("w", encoding="utf-8")
        run_program(cpu, max_ticks=args.max_ticks, log=log_file)
    except CpuFault as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        if log_file is not None:
            log_file.close()

    if not cpu.halted:
        print("упёрлись в лимит тактов — HALT не был", file=sys.stderr)
        return 1
    print(f"HALT ticks={cpu.ticks} PC={cpu.pc} SP=0x{cpu.sp:X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
