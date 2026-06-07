#!/usr/bin/env python3
"""Перегенерация golden-артефактов: python scripts/regenerate_golden.py [case ...]"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from golden_support import GOLDEN_ROOT, write_golden_artifacts  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        cases = argv[1:]
    else:
        cases = [
            case_dir.name
            for case_dir in sorted(GOLDEN_ROOT.iterdir())
            if case_dir.is_dir() and (case_dir / "source.tv").is_file()
        ]

    for case in cases:
        print(f"regenerate {case}...", flush=True)
        write_golden_artifacts(case)
        out = (GOLDEN_ROOT / case / "output.txt").read_bytes()
        print(f"  output: {out!r}", flush=True)
    print(f"done: {len(cases)} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
