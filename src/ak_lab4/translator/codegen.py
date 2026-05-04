"""Генерация машинных слов из AST (литералы, арифметика, setq, if)."""

from __future__ import annotations

from ak_lab4.isa import Opcode, pack_word
from ak_lab4.translator.ast import Expr, IntLit, SList, StrLit, Symbol

# 24-бит signed immediate в push_imm
IMM24_MIN: int = -(2**23)
IMM24_MAX: int = 2**23 - 1

_ARITH: dict[str, Opcode] = {
    "+": Opcode.ADD,
    "-": Opcode.SUB,
    "*": Opcode.MUL,
    "/": Opcode.DIV,
    "mod": Opcode.MOD,
}


class CodegenError(ValueError):
    """Неподдерживаемая конструкция или неверная арность."""


def _check_imm24(v: int) -> int:
    if v < IMM24_MIN or v > IMM24_MAX:
        msg = f"Литерал {v} вне диапазона 24-бит signed ({IMM24_MIN}…{IMM24_MAX})"
        raise CodegenError(msg)
    return v


def _collect_global_slots(e: Expr) -> dict[str, int]:
    """Имена из `(setq name …)` в preorder; каждому имя — слово статики с адреса 0."""

    order: list[str] = []

    def walk(ex: Expr) -> None:
        match ex:
            case SList(items):
                if (
                    len(items) >= 3
                    and isinstance(items[0], Symbol)
                    and items[0].name == "setq"
                    and isinstance(items[1], Symbol)
                ):
                    order.append(items[1].name)
                for it in items:
                    walk(it)
            case _:
                pass

    walk(e)
    slots: dict[str, int] = {}
    nxt = 0
    for nm in order:
        if nm not in slots:
            slots[nm] = nxt
            nxt += 1
    return slots


def _emit_n_ary(
    op: Opcode,
    args: tuple[Expr, ...],
    name: str,
    slots: dict[str, int],
) -> list[int]:
    if len(args) < 2:
        raise CodegenError(f"{name} требует минимум два аргумента")
    words: list[int] = []
    words.extend(_emit(args[0], slots))
    words.extend(_emit(args[1], slots))
    words.append(pack_word(op, 0))
    for extra in args[2:]:
        words.extend(_emit(extra, slots))
        words.append(pack_word(op, 0))
    return words


def _emit(e: Expr, slots: dict[str, int]) -> list[int]:
    """Слова без финального HALT (для вложенных выражений)."""
    match e:
        case IntLit(v):
            v2 = _check_imm24(v)
            return [pack_word(Opcode.PUSH_IMM, v2)]
        case StrLit(_):
            raise CodegenError("Строковые литералы пока не генерируются")
        case Symbol(name):
            addr = slots.get(name)
            if addr is None:
                raise CodegenError(f"Неизвестный символ «{name}» (нет setq в программе)")
            return [
                pack_word(Opcode.PUSH_IMM, _check_imm24(addr)),
                pack_word(Opcode.LOAD, 0),
            ]
        case SList(items):
            if not items:
                raise CodegenError("Пустой список () недопустим как выражение")
            head, *args = items
            if not isinstance(head, Symbol):
                raise CodegenError("Вызов: голова списка должна быть символом")
            if head.name == "setq":
                if len(args) != 2:
                    raise CodegenError("setq ожидает ровно два аргумента (имя и выражение)")
                sym_el, rhs = args
                if not isinstance(sym_el, Symbol):
                    raise CodegenError("setq: первый аргумент должен быть символом")
                addr = slots.get(sym_el.name)
                if addr is None:
                    raise CodegenError(f"Внутренняя ошибка: слот для «{sym_el.name}» не найден")
                words = [
                    pack_word(Opcode.PUSH_IMM, _check_imm24(addr)),
                    *_emit(rhs, slots),
                    pack_word(Opcode.STORE, 0),
                    pack_word(Opcode.PUSH_IMM, _check_imm24(addr)),
                    pack_word(Opcode.LOAD, 0),
                ]
                return words
            if head.name == "if":
                if len(args) != 3:
                    raise CodegenError("if ожидает ровно три аргумента (условие then else)")
                pred_e, then_e, else_e = args
                words: list[int] = []
                words.extend(_emit(pred_e, slots))
                jz_ix = len(words)
                words.append(pack_word(Opcode.JZ, 0))
                words.extend(_emit(then_e, slots))
                jmp_ix = len(words)
                words.append(pack_word(Opcode.JMP, 0))
                else_pc = len(words)
                words[jz_ix] = pack_word(Opcode.JZ, else_pc)
                words.extend(_emit(else_e, slots))
                end_pc = len(words)
                words[jmp_ix] = pack_word(Opcode.JMP, end_pc)
                return words
            op = _ARITH.get(head.name)
            if op is not None:
                return _emit_n_ary(op, tuple(args), head.name, slots)
            raise CodegenError(f"Неизвестная форма: ({head.name} …)")


def compile_program(expr: Expr) -> list[int]:
    """Одно выражение-программа: код и завершающий HALT."""
    slots = _collect_global_slots(expr)
    return _emit(expr, slots) + [pack_word(Opcode.HALT, 0)]
