"""CLI транслятора"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ak_lab4.loader import write_words_le
from ak_lab4.translator import CodegenError, LexError, ParseError, compile_forms, parse_many

_CLI_EPILOG = """\
Пример:
  python -m ak_lab4.translator prog.tv -o code.bin --data-out data.bin
  python -m ak_lab4.simulator code.bin data.bin

Ввод порта:
  ... simulator ... --input stdin.bin

Trap (JSON массив событий по тактам):
  ... simulator ... --schedule irq.json
  см. docs/io-trap-port.md
"""


def write_listing(path: Path, words: list[int]) -> None:
    lines = [f"{i} - {w:08X}" for i, w in enumerate(words)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="file -> code.bin; несколько форм подряд склеиваются как progn",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_CLI_EPILOG,
    )
    p.add_argument("input", type=Path, help="Исходник")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("code.bin"),
        help="Память команд (default: code.bin)",
    )
    p.add_argument(
        "--data-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="data.bin; нужен, если в программе есть строковые литералы",
    )
    p.add_argument(
        "--listing",
        type=Path,
        default=None,
        metavar="PATH",
        help="листинг команд",
    )
    args = p.parse_args(argv)

    try:
        text = args.input.read_text(encoding="utf-8")
    except OSError as e:
        print(f"{args.input}: {e}", file=sys.stderr)
        return 2

    try:
        forms = parse_many(text)
    except (LexError, ParseError) as e:
        print(str(e), file=sys.stderr)
        return 1

    if len(forms) == 0:
        print("ошибка: пустой файл", file=sys.stderr)
        return 1

    try:
        prog = compile_forms(forms)
    except CodegenError as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        write_words_le(args.output, prog.code)
        if prog.data:
            if args.data_out is None:
                print(
                    "ошибка: укажите --data-out (в программе есть литералы в сегменте данных)",
                    file=sys.stderr,
                )
                return 1
            write_words_le(args.data_out, prog.data)
        elif args.data_out is not None:
            write_words_le(args.data_out, [])
        if args.listing is not None:
            write_listing(args.listing, prog.code)
    except OSError as e:
        print(e, file=sys.stderr)
        return 2

    return 0
