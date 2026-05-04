"""Генерация машинных слов: литералы, arith, setq, if, eq, progn, defun (0 арг), вызов."""

from __future__ import annotations

from ak_lab4.isa import Opcode, pack_word
from ak_lab4.translator.ast import Expr, IntLit, SList, StrLit, Symbol

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


def _collect_slots_from_forms(forms: tuple[Expr, ...]) -> dict[str, int]:
    """Слоты для setq: preorder по всем верхнеуровневым формам и телам defun."""

    order: list[str] = []

    def walk(ex: Expr) -> None:
        match ex:
            case SList(items):
                if (
                    len(items) >= 4
                    and isinstance(items[0], Symbol)
                    and items[0].name == "defun"
                ):
                    walk(items[3])
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

    for f in forms:
        walk(f)
    slots: dict[str, int] = {}
    nxt = 0
    for nm in order:
        if nm not in slots:
            slots[nm] = nxt
            nxt += 1
    return slots


def _is_defun_form(e: Expr) -> bool:
    return (
        isinstance(e, SList)
        and len(e.items) >= 4
        and isinstance(e.items[0], Symbol)
        and e.items[0].name == "defun"
        and isinstance(e.items[1], Symbol)
        and isinstance(e.items[2], SList)
    )


def _parse_defun_zero_args(d: SList) -> tuple[str, Expr]:
    if len(d.items) != 4:
        raise CodegenError("defun: ожидается (defun name () тело) — одно выражение в теле")
    _kw, name_el, params_el, body = d.items
    if not isinstance(name_el, Symbol):
        raise CodegenError("defun: имя функции должно быть символом")
    if not isinstance(params_el, SList) or len(params_el.items) != 0:
        raise CodegenError("defun: пока только пустой список параметров ()")
    return name_el.name, body


def _split_defuns_first(forms: tuple[Expr, ...]) -> tuple[tuple[SList, ...], tuple[Expr, ...]]:
    defuns: list[SList] = []
    mains: list[Expr] = []
    stage = "def"
    for f in forms:
        if _is_defun_form(f):
            if stage == "main":
                raise CodegenError("defun должен быть объявлен до основного кода (вызовов)")
            defuns.append(f)  # type: ignore[arg-type]
        else:
            stage = "main"
            mains.append(f)
    return tuple(defuns), tuple(mains)


def _emit_n_ary(
    op: Opcode,
    args: tuple[Expr, ...],
    name: str,
    slots: dict[str, int],
    pc0: int,
    funcs: dict[str, int] | None,
) -> list[int]:
    if len(args) < 2:
        raise CodegenError(f"{name} требует минимум два аргумента")
    out: list[int] = []
    cur = pc0
    out.extend(_emit(args[0], slots, cur, funcs))
    cur = pc0 + len(out)
    out.extend(_emit(args[1], slots, cur, funcs))
    cur = pc0 + len(out)
    out.append(pack_word(op, 0))
    for extra in args[2:]:
        cur = pc0 + len(out)
        out.extend(_emit(extra, slots, cur, funcs))
        out.append(pack_word(op, 0))
    return out


def _emit(e: Expr, slots: dict[str, int], pc0: int, funcs: dict[str, int] | None) -> list[int]:
    """Слова без HALT; funcs — абсолютные PC функций (для CALL), опционально."""
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
            if head.name == "progn":
                if not args:
                    raise CodegenError("progn требует хотя бы одно выражение")
                parts: list[int] = []
                cur = pc0
                for i, ex in enumerate(args):
                    segment = _emit(ex, slots, cur, funcs)
                    parts.extend(segment)
                    cur = pc0 + len(parts)
                    if i < len(args) - 1:
                        parts.append(pack_word(Opcode.DROP, 0))
                        cur = pc0 + len(parts)
                return parts
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
                    + _emit(rhs, slots, rhs_start, funcs)
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
                pred_c = _emit(pred_e, slots, pc0, funcs)
                jz_pc = pc0 + len(pred_c)
                then_start = jz_pc + 1
                then_c = _emit(then_e, slots, then_start, funcs)
                jmp_pc = then_start + len(then_c)
                else_start = jmp_pc + 1
                else_c = _emit(else_e, slots, else_start, funcs)
                end_pc = else_start + len(else_c)
                return (
                    pred_c
                    + [pack_word(Opcode.JZ, else_start)]
                    + then_c
                    + [pack_word(Opcode.JMP, end_pc)]
                    + else_c
                )
            if head.name in ("eq", "="):
                if len(args) != 2:
                    raise CodegenError("eq и = ожидают ровно два аргумента")
                left = _emit(args[0], slots, pc0, funcs)
                right = _emit(args[1], slots, pc0 + len(left), funcs)
                return left + right + [pack_word(Opcode.EQ, 0)]
            op = _ARITH.get(head.name)
            if op is not None:
                return _emit_n_ary(op, tuple(args), head.name, slots, pc0, funcs)
            if funcs is not None and head.name in funcs:
                if args:
                    raise CodegenError("Вызов функции: пока только без аргументов, (имя)")
                return [pack_word(Opcode.CALL, funcs[head.name])]
            raise CodegenError(f"Неизвестная форма: ({head.name} …)")


def _compile_with_defuns(defuns: tuple[SList, ...], mains: tuple[Expr, ...]) -> list[int]:
    all_forms = tuple(defuns) + mains
    slots = _collect_slots_from_forms(all_forms)
    words: list[int] = []
    jmp_ix = 0
    words.append(pack_word(Opcode.JMP, 0))

    func_targets: dict[str, int] = {}
    seen_names: set[str] = set()

    for d in defuns:
        name, body = _parse_defun_zero_args(d)
        if name in seen_names:
            raise CodegenError(f"Повторное определение функции «{name}»")
        seen_names.add(name)
        start_pc = len(words)
        func_targets[name] = start_pc
        words.extend(_emit(body, slots, start_pc, func_targets))
        words.append(pack_word(Opcode.SWAP, 0))
        words.append(pack_word(Opcode.RET, 0))

    main_start = len(words)
    words[jmp_ix] = pack_word(Opcode.JMP, main_start)

    main_expr = mains[0] if len(mains) == 1 else SList((Symbol("progn"),) + mains)
    words.extend(_emit(main_expr, slots, main_start, func_targets))
    words.append(pack_word(Opcode.HALT, 0))
    return words


def compile_program(expr: Expr) -> list[int]:
    """Одно выражение-программа: код и завершающий HALT."""
    slots = _collect_slots_from_forms((expr,))
    return _emit(expr, slots, 0, None) + [pack_word(Opcode.HALT, 0)]


def compile_forms(forms: tuple[Expr, ...]) -> list[int]:
    """Несколько верхнеуровневых форм; при наличии defun — модуль с JMP на main."""
    if not forms:
        raise CodegenError("Нет форм для компиляции")
    defuns, mains = _split_defuns_first(forms)
    if defuns:
        if not mains:
            raise CodegenError("После defun нужно хотя бы одно основное выражение")
        return _compile_with_defuns(defuns, mains)
    if len(forms) == 1:
        return compile_program(forms[0])
    wrapped = SList((Symbol("progn"),) + tuple(forms))
    slots = _collect_slots_from_forms(forms)
    return _emit(wrapped, slots, 0, None) + [pack_word(Opcode.HALT, 0)]
