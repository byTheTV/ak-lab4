from __future__ import annotations

from pathlib import Path

from ak_lab4.loader import load_words_le
from ak_lab4.translator import compile_program, parse
from ak_lab4.translator.cli import main as translator_main


def test_cli_compiles_add(tmp_path: Path) -> None:
    src = tmp_path / "p.lisp"
    src.write_text("(+ 1 2)\n", encoding="utf-8")
    out = tmp_path / "code.bin"
    rc = translator_main([str(src), "-o", str(out)])
    assert rc == 0
    assert load_words_le(out) == compile_program(parse("(+ 1 2)")).code
