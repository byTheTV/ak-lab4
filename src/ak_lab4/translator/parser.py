"""Разбор S-выражений в AST."""

from __future__ import annotations

from ak_lab4.translator.ast import Expr, IntLit, SList, StrLit, Symbol
from ak_lab4.translator.lexer import SourceLoc, TokKind, Token, tokenize


class ParseError(ValueError):
    def __init__(self, message: str, loc: SourceLoc | None = None) -> None:
        if loc is not None:
            super().__init__(f"{message} at line {loc.line}, col {loc.col}")
        else:
            super().__init__(message)
        self.loc = loc


def parse(source: str) -> Expr:
    """Одно S-выражение (одна форма)."""
    toks = tokenize(source)
    p = _Parser(toks)
    e = p.parse_expr()
    p.expect_eof()
    return e


def parse_many(source: str) -> tuple[Expr, ...]:
    """Несколько верхнеуровневых форм подряд."""
    toks = tokenize(source)
    p = _Parser(toks)
    items: list[Expr] = []
    while not p.done():
        items.append(p.parse_expr())
    return tuple(items)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._t = tokens
        self._i = 0

    def done(self) -> bool:
        return self._i >= len(self._t)

    def _peek(self) -> Token | None:
        if self._i >= len(self._t):
            return None
        return self._t[self._i]

    def _take(self) -> Token:
        if self._i >= len(self._t):
            raise ParseError("Неожиданный конец ввода")
        t = self._t[self._i]
        self._i += 1
        return t

    def expect_eof(self) -> None:
        if not self.done():
            t = self._peek()
            assert t is not None
            raise ParseError("Лишние токены после выражения", t.loc)

    def parse_expr(self) -> Expr:
        t = self._peek()
        if t is None:
            raise ParseError("Ожидалось выражение", None)
        if t.kind == TokKind.LPAREN:
            return self._parse_list()
        if t.kind == TokKind.INT:
            self._take()
            assert t.int_value is not None
            return IntLit(t.int_value)
        if t.kind == TokKind.STRING:
            return self._parse_string_literal()
        if t.kind == TokKind.SYMBOL:
            self._take()
            return Symbol(t.text)
        if t.kind == TokKind.RPAREN:
            raise ParseError("Лишняя закрывающая скобка", t.loc)
        raise ParseError(f"Неожиданный токен {t.kind}", t.loc)

    def _parse_list(self) -> Expr:
        open_tok = self._take()
        assert open_tok.kind == TokKind.LPAREN
        parts: list[Expr] = []
        while True:
            t = self._peek()
            if t is None:
                raise ParseError("Не хватает ')'", open_tok.loc)
            if t.kind == TokKind.RPAREN:
                self._take()
                return SList(tuple(parts))
            parts.append(self.parse_expr())

    def _parse_string_literal(self) -> StrLit:
        t = self._take()
        assert t.kind == TokKind.STRING
        raw = t.text
        assert raw.startswith('"') and raw.endswith('"')
        inner = raw[1:-1]
        out: list[str] = []
        j = 0
        while j < len(inner):
            if inner[j] == "\\":
                if j + 1 >= len(inner):
                    raise ParseError("Незавершённый escape", t.loc)
                nxt = inner[j + 1]
                if nxt == "n":
                    out.append("\n")
                else:
                    out.append(nxt)
                j += 2
            else:
                out.append(inner[j])
                j += 1
        return StrLit("".join(out))


def parse_file(path: str) -> tuple[Expr, ...]:
    """Прочитать файл и разобрать все верхнеуровневые формы."""
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    return parse_many(text)
