"""AST до семантики/codegen"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntLit:
    value: int


@dataclass(frozen=True, slots=True)
class StrLit:
    value: str


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str


@dataclass(frozen=True, slots=True)
class SList:
    """вызов, спецформа или вложенный список"""

    items: tuple[Expr, ...]


Expr = IntLit | StrLit | Symbol | SList


def expr_repr(e: Expr) -> str:
    """строка для тестов/golden, без id объектов"""
    match e:
        case IntLit(v):
            return f"(int {v})"
        case StrLit(s):
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            return f'(str "{escaped}")'
        case Symbol(name):
            return f"(sym {name})"
        case SList(items):
            inner = " ".join(expr_repr(x) for x in items)
            return f"(list {inner})"
