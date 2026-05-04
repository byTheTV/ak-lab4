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
    pc0: int,
) -> list[int]:
    if len(args) < 2:
        raise CodegenError(f"{name} требует минимум два аргумента")
    out: list[int] = []
    cur = pc0
    out.extend(_emit(args[0], slots, cur))
    cur = pc0 + len(out)
    out.extend(_emit(args[1], slots, cur))
    cur = pc0 + len(out)
    out.append(pack_word(op, 0))
    for extra in args[2:]:
        cur = pc0 + len(out)
        out.extend(_emit(extra, slots, cur))
        out.append(pack_word(op, 0))
    return out


def _emit(e: Expr, slots: dict[str, int], pc0: int) -> list[int]:
    """Слова без HALT; `pc0` — абсолютный индекс первой инструкции в общем IM."""
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
                head_w = [pack_word(Opcode.PUSH_IMM, _check_imm24(addr))]
                rhs_start = pc0 + 1
                return (
                    head_w
                    + _emit(rhs, slots, rhs_start)
                    + [
                        pack_word(Opcode.STORE, 0),
                        pack_word(Opcode.PUSH_IMM, _check_imm24(addr)),
                        pack_word(Opcode.LOAD, 0),
                    ]
                )
            if head.name == "if":
                if len(args) != 3:
                    raise CodegenError("if ожидает ровно три аргумента (условие then else)")
                pred_e, then_e, else_e = args
                pred_c = _emit(pred_e, slots, pc0)
                jz_pc = pc0 + len(pred_c)
                then_start = jz_pc + 1
                then_c = _emit(then_e, slots, then_start)
                jmp_pc = then_start + len(then_c)
                else_start = jmp_pc + 1
                else_c = _emit(else_e, slots, else_start)
                end_pc = else_start + len(else_c)
                return (
                    pred_c
                    + [pack_word(Opcode.JZ, else_start)]
                    + then_c
                    + [pack_word(Opcode.JMP, end_pc)]
                    + else_c
                )
            op = _ARITH.get(head.name)
            if op is not None:
                return _emit_n_ary(op, tuple(args), head.name, slots, pc0)
            raise CodegenError(f"Неизвестная форма: ({head.name} …)")


def compile_program(expr: Expr) -> list[int]:
    """Одно выражение-программа: код и завершающий HALT."""
    slots = _collect_global_slots(expr)
    return _emit(expr, slots, 0) + [pack_word(Opcode.HALT, 0)]
