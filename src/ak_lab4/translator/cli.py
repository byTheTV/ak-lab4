"""Консольный интерфейс транслятора (вызов из `__main__` или тестов)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ak_lab4.loader import write_words_le
from ak_lab4.translator import CodegenError, LexError, ParseError, compile_program, parse_many


def write_listing(path: Path, words: list[int]) -> None:
    """Текстовый листинг: `<addr> - <HEX8>` по строке на слово."""
    lines = [f"{i} - {w:08X}" for i, w in enumerate(words)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Транслятор Lisp → code.bin (одна верхнеуровневая форма)."
    )
    p.add_argument("input", type=Path, help="Исходный .lisp")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("code.bin"),
        help="Выход: память команд (по умолчанию code.bin)",
    )
    p.add_argument(
        "--data-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Выход: память данных (пустой сегмент, если указан)",
    )
    p.add_argument(
        "--listing",
        type=Path,
        default=None,
        metavar="PATH",
        help="Текстовый hex-листинг",
    )
    args = p.parse_args(argv)

    try:
        text = args.input.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Ошибка чтения: {e}", file=sys.stderr)
        return 2

    try:
        forms = parse_many(text)
    except (LexError, ParseError) as e:
        print(str(e), file=sys.stderr)
        return 1

    if len(forms) == 0:
        print("Ошибка: пустой или только пробельный вход", file=sys.stderr)
        return 1
    if len(forms) != 1:
        print(
            f"Ошибка: ожидается ровно одна верхнеуровневая форма, получено {len(forms)}",
            file=sys.stderr,
        )
        return 1

    try:
        words = compile_program(forms[0])
    except CodegenError as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        write_words_le(args.output, words)
        if args.data_out is not None:
            write_words_le(args.data_out, [])
        if args.listing is not None:
            write_listing(args.listing, words)
    except OSError as e:
        print(f"Ошибка записи: {e}", file=sys.stderr)
        return 2

    return 0
