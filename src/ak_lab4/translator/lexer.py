"""Лексер для S-выражений"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokKind(Enum):
    LPAREN = auto()
    RPAREN = auto()
    INT = auto()
    STRING = auto()
    SYMBOL = auto()


@dataclass(frozen=True, slots=True)
class SourceLoc:
    offset: int
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokKind
    text: str
    loc: SourceLoc
    # у INT — значение, у остальных не используется
    int_value: int | None = None


class LexError(ValueError):
    def __init__(self, message: str, loc: SourceLoc) -> None:
        super().__init__(f"{message} at line {loc.line}, col {loc.col}")
        self.loc = loc


def tokenize(source: str) -> list[Token]:
    """Токены по тексту, пробелы и комментарии ; … до конца строки пропускаются"""
    i = 0
    line = 1
    col = 1
    out: list[Token] = []
    n = len(source)

    def loc() -> SourceLoc:
        return SourceLoc(offset=i, line=line, col=col)

    while i < n:
        c = source[i]
        if c in " \t\r\n":
            if c == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1
            continue
        if c == ";":
            while i < n and source[i] != "\n":
                i += 1
                col += 1
            continue
        start_loc = loc()
        if c == "(":
            out.append(Token(TokKind.LPAREN, "(", start_loc))
            i += 1
            col += 1
            continue
        if c == ")":
            out.append(Token(TokKind.RPAREN, ")", start_loc))
            i += 1
            col += 1
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    if j + 1 >= n:
                        raise LexError(
                            "escape обрывается в конце строки",
                            SourceLoc(j, line, col + (j - i)),
                        )
                    j += 2
                    continue
                if source[j] == '"':
                    out.append(Token(TokKind.STRING, source[i : j + 1], start_loc, None))
                    span = j + 1 - i
                    i = j + 1
                    col += span
                    break
                j += 1
            else:
                raise LexError("строка без закрывающей кавычки", start_loc)
            continue

        # число: [0-9]+ или явный знак +/-
        if c.isdigit() or (c in "+-" and i + 1 < n and source[i + 1].isdigit()):
            sign = 1
            j = i
            if c in "+-":
                if c == "-":
                    sign = -1
                j += 1
            start_digits = j
            if j >= n or not source[j].isdigit():
                raise LexError("после знака +/- нужны цифры", start_loc)
            while j < n and source[j].isdigit():
                j += 1
            num_str = source[i:j]
            val = sign * int(source[start_digits:j])
            out.append(Token(TokKind.INT, num_str, start_loc, val))
            col += j - i
            i = j
            continue

        # символ: до разделителя
        j = i
        while j < n and source[j] not in ' \t\r\n();"':
            j += 1
        sym = source[i:j]
        if not sym:
            raise LexError(f"лишний символ {c!r}", start_loc)
        out.append(Token(TokKind.SYMBOL, sym, start_loc, None))
        col += j - i
        i = j

    return out
