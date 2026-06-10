#!/usr/bin/env python3
"""Пересобрать golden/*.yml из examples/<name>.lisp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from golden_support import (  # noqa: E402
    EXAMPLES_ROOT,
    example_lisp_path,
    regenerate_golden_yml,
)


def _discover_example_names() -> list[str]:
    return sorted(p.stem for p in EXAMPLES_ROOT.glob("*.lisp"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "names",
        nargs="*",
        help="имя кейса (без .lisp); по умолчанию — все examples/*.lisp",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="лимит тактов симуляции (по умолчанию из golden_support)",
    )
    args = parser.parse_args(argv)
    names = args.names or _discover_example_names()
    if not names:
        print("нет examples/*.lisp", file=sys.stderr)
        return 1

    for name in names:
        path = example_lisp_path(name)
        if not path.is_file():
            print(f"пропуск: нет {path}", file=sys.stderr)
            continue
        out = regenerate_golden_yml(name, max_ticks=args.max_ticks)
        print(f"обновлён {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
