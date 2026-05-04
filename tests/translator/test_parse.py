from __future__ import annotations

import pytest

from ak_lab4.translator import (
    LexError,
    ParseError,
    expr_repr,
    parse,
    parse_many,
    tokenize,
)


def test_tokenize_plus_one_two() -> None:
    toks = tokenize("(+ 1 2)")
    kinds = [t.kind.name for t in toks]
    assert kinds == ["LPAREN", "SYMBOL", "INT", "INT", "RPAREN"]


def test_parse_plus_one_two() -> None:
    e = parse("(+ 1 2)")
    assert expr_repr(e) == "(list (sym +) (int 1) (int 2))"


def test_parse_signed_and_plus_prefix_int() -> None:
    assert expr_repr(parse("(-7)")) == "(list (int -7))"
    assert expr_repr(parse("(+42)")) == "(list (int 42))"


def test_parse_nested() -> None:
    e = parse("((a b) c)")
    assert expr_repr(e) == "(list (list (sym a) (sym b)) (sym c))"


def test_parse_many_top_level() -> None:
    forms = parse_many("(setq x 1) (setq y 2)")
    assert len(forms) == 2
    assert expr_repr(forms[0]) == "(list (sym setq) (sym x) (int 1))"
    assert expr_repr(forms[1]) == "(list (sym setq) (sym y) (int 2))"


def test_comment_skipped() -> None:
    e = parse(
        """
        ; comment
        (42)
        """
    )
    assert expr_repr(e) == "(list (int 42))"


def test_string_escape() -> None:
    e = parse(r'("a\"b")')
    assert expr_repr(e) == r'(list (str "a\"b"))'


def test_lex_unterminated_string() -> None:
    with pytest.raises(LexError):
        tokenize('"hello')


def test_parse_unbalanced() -> None:
    with pytest.raises(ParseError):
        parse("(a b")
