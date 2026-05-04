from __future__ import annotations

from pathlib import Path

from ak_lab4.loader import load_words_le
from ak_lab4.translator import compile_forms, compile_program, parse, parse_many
from ak_lab4.translator.cli import main as translator_main


def test_cli_compiles_add(tmp_path: Path) -> None:
    src = tmp_path / "p.lisp"
    src.write_text("(+ 1 2)\n", encoding="utf-8")
    out = tmp_path / "code.bin"
    rc = translator_main([str(src), "-o", str(out)])
    assert rc == 0
    assert load_words_le(out) == compile_program(parse("(+ 1 2)"))


def test_cli_compiles_multiple_forms_as_progn(tmp_path: Path) -> None:
    src = tmp_path / "p.lisp"
    src.write_text("(setq a 1)(+ a 2)\n", encoding="utf-8")
    out = tmp_path / "code.bin"
    rc = translator_main([str(src), "-o", str(out)])
    assert rc == 0
    many = parse_many(src.read_text(encoding="utf-8"))
    assert load_words_le(out) == compile_forms(many)
    assert load_words_le(out) == compile_program(parse("(progn (setq a 1) (+ a 2))"))


def test_cli_listing_and_data_out(tmp_path: Path) -> None:
    src = tmp_path / "p.lisp"
    src.write_text("42", encoding="utf-8")
    code = tmp_path / "c.bin"
    data = tmp_path / "d.bin"
    lst = tmp_path / "c.lst"
    rc = translator_main(
        [str(src), "-o", str(code), "--data-out", str(data), "--listing", str(lst)]
    )
    assert rc == 0
    assert data.read_bytes() == b""
    lines = [ln for ln in lst.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == len(load_words_le(code))
    assert load_words_le(code) == compile_program(parse("42"))
