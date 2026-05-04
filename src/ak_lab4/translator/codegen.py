"""Генерация машинных слов из AST (подмножество: целые, n-арный +)."""

from __future__ import annotations

from ak_lab4.isa import Opcode, pack_word
from ak_lab4.translator.ast import Expr, IntLit, SList, StrLit, Symbol

# 24-бит signed immediate в push_imm
IMM24_MIN: int = -(2**23)
IMM24_MAX: int = 2**23 - 1


class CodegenError(ValueError):
    """Неподдерживаемая конструкция или неверная арность."""


def _check_imm24(v: int) -> int:
    if v < IMM24_MIN or v > IMM24_MAX:
        msg = f"Литерал {v} вне диапазона 24-бит signed ({IMM24_MIN}…{IMM24_MAX})"
        raise CodegenError(msg)
    return v


def _emit(e: Expr) -> list[int]:
    """Слова без финального HALT (для вложенных выражений)."""
    match e:
        case IntLit(v):
            v2 = _check_imm24(v)
            return [pack_word(Opcode.PUSH_IMM, v2)]
        case StrLit(_):
            raise CodegenError("Строковые литералы пока не генерируются")
        case Symbol(name):
            raise CodegenError(f"Символ «{name}» без контекста (переменные — позже)")
        case SList(items):
            if not items:
                raise CodegenError("Пустой список () недопустим как выражение")
            head, *args = items
            if not isinstance(head, Symbol):
                raise CodegenError("Вызов: голова списка должна быть символом")
            if head.name == "+":
                if len(args) < 2:
                    raise CodegenError("+ требует минимум два аргумента")
                words: list[int] = []
                words.extend(_emit(args[0]))
                words.extend(_emit(args[1]))
                words.append(pack_word(Opcode.ADD, 0))
                for extra in args[2:]:
                    words.extend(_emit(extra))
                    words.append(pack_word(Opcode.ADD, 0))
                return words
            raise CodegenError(f"Неизвестная форма: ({head.name} …)")


def compile_program(expr: Expr) -> list[int]:
    """Одно выражение-программа: код и завершающий HALT."""
    return _emit(expr) + [pack_word(Opcode.HALT, 0)]
