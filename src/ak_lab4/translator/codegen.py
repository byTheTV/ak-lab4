"""Генерация машинных слов: arith, setq, if, eq, progn, defun с параметрами, CALL."""

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


def _collect_bindings(
    forms: tuple[Expr, ...],
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """Глобальные слоты setq + слоты параметров (fname, pname) → адрес DM."""

    order_setq: list[str] = []

    def walk(ex: Expr) -> None:
        match ex:
            case SList(items):
                if len(items) >= 4 and isinstance(items[0], Symbol) and items[0].name == "defun":
                    walk(items[3])
                if (
                    len(items) >= 3
                    and isinstance(items[0], Symbol)
                    and items[0].name == "setq"
                    and isinstance(items[1], Symbol)
                ):
                    order_setq.append(items[1].name)
                for it in items:
                    walk(it)
            case _:
                pass

    for f in forms:
        walk(f)

    global_slots: dict[str, int] = {}
    nxt = 0
    for nm in order_setq:
        if nm not in global_slots:
            global_slots[nm] = nxt
            nxt += 1

    param_slot: dict[tuple[str, str], int] = {}
    for f in forms:
        if _is_defun_form(f):
            assert isinstance(f, SList)
            fname, params, _ = _parse_defun_full(f)
            for p in params:
                key = (fname, p)
                if key in param_slot:
                    raise CodegenError(f"defun «{fname}»: повтор имени параметра «{p}»")
                param_slot[key] = nxt
                nxt += 1

    return global_slots, param_slot


def _slot_addr(
    name: str,
    global_slots: dict[str, int],
    param_scope: dict[str, int] | None,
) -> int:
    if param_scope is not None and name in param_scope:
        return param_scope[name]
    if name in global_slots:
        return global_slots[name]
    raise CodegenError(f"Неизвестный символ «{name}»")


def _is_defun_form(e: Expr) -> bool:
    return (
        isinstance(e, SList)
        and len(e.items) >= 4
        and isinstance(e.items[0], Symbol)
        and e.items[0].name == "defun"
        and isinstance(e.items[1], Symbol)
        and isinstance(e.items[2], SList)
    )


def _parse_defun_full(d: SList) -> tuple[str, tuple[str, ...], Expr]:
    if len(d.items) != 4:
        raise CodegenError("defun: ожидается (defun имя (параметры ...) одно_тело)")
    _kw, name_el, params_el, body = d.items
    if not isinstance(name_el, Symbol):
        raise CodegenError("defun: имя функции должно быть символом")
    if not isinstance(params_el, SList):
        raise CodegenError("defun: список параметров должен быть в скобках")
    params: list[str] = []
    for item in params_el.items:
        if not isinstance(item, Symbol):
            raise CodegenError("defun: каждый параметр — символ")
        params.append(item.name)
    if len(set(params)) != len(params):
        raise CodegenError("defun: имена параметров должны быть различны")
    return name_el.name, tuple(params), body


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
    global_slots: dict[str, int],
    pc0: int,
    funcs: dict[str, int] | None,
    param_scope: dict[str, int] | None,
    func_param_sig: dict[str, tuple[str, ...]] | None,
    param_slot_addr: dict[tuple[str, str], int] | None,
) -> list[int]:
    if len(args) < 2:
        raise CodegenError(f"{name} требует минимум два аргумента")
    ctx = (funcs, param_scope, func_param_sig, param_slot_addr)
    out: list[int] = []
    cur = pc0
    out.extend(_emit(args[0], global_slots, cur, *ctx))
    cur = pc0 + len(out)
    out.extend(_emit(args[1], global_slots, cur, *ctx))
    cur = pc0 + len(out)
    out.append(pack_word(op, 0))
    for extra in args[2:]:
        cur = pc0 + len(out)
        out.extend(_emit(extra, global_slots, cur, *ctx))
        out.append(pack_word(op, 0))
    return out


def _emit(
    e: Expr,
    global_slots: dict[str, int],
    pc0: int,
    funcs: dict[str, int] | None,
    param_scope: dict[str, int] | None = None,
    func_param_sig: dict[str, tuple[str, ...]] | None = None,
    param_slot_addr: dict[tuple[str, str], int] | None = None,
) -> list[int]:
    """func_param_sig / param_slot_addr нужны для вызовов с аргументами."""

    match e:
        case IntLit(v):
            v2 = _check_imm24(v)
            return [pack_word(Opcode.PUSH_IMM, v2)]
        case StrLit(_):
            raise CodegenError("Строковые литералы пока не генерируются")
        case Symbol(name):
            addr = _slot_addr(name, global_slots, param_scope)
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
                    segment = _emit(
                        ex,
                        global_slots,
                        cur,
                        funcs,
                        param_scope,
                        func_param_sig,
                        param_slot_addr,
                    )
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
                addr = _slot_addr(sym_el.name, global_slots, param_scope)
                head_w = [pack_word(Opcode.PUSH_IMM, _check_imm24(addr))]
                rhs_start = pc0 + 1
                return (
                    head_w
                    + _emit(
                        rhs,
                        global_slots,
                        rhs_start,
                        funcs,
                        param_scope,
                        func_param_sig,
                        param_slot_addr,
                    )
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
                pred_c = _emit(
                    pred_e,
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                )
                jz_pc = pc0 + len(pred_c)
                then_start = jz_pc + 1
                then_c = _emit(
                    then_e,
                    global_slots,
                    then_start,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                )
                jmp_pc = then_start + len(then_c)
                else_start = jmp_pc + 1
                else_c = _emit(
                    else_e,
                    global_slots,
                    else_start,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                )
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
                left = _emit(
                    args[0],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                )
                right = _emit(
                    args[1],
                    global_slots,
                    pc0 + len(left),
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                )
                return left + right + [pack_word(Opcode.EQ, 0)]
            op = _ARITH.get(head.name)
            if op is not None:
                return _emit_n_ary(
                    op,
                    tuple(args),
                    head.name,
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                )
            if funcs is not None and head.name in funcs:
                if func_param_sig is None or param_slot_addr is None:
                    raise CodegenError("внутренняя ошибка: нет таблицы параметров для CALL")
                sig = func_param_sig[head.name]
                if len(args) != len(sig):
                    raise CodegenError(
                        f"«{head.name}»: ожидается {len(sig)} арг., передано {len(args)}",
                    )
                out: list[int] = []
                cur = pc0
                for arg_e, pname in zip(args, sig, strict=True):
                    ps_addr = param_slot_addr[head.name, pname]
                    out.append(pack_word(Opcode.PUSH_IMM, _check_imm24(ps_addr)))
                    cur = pc0 + len(out)
                    out.extend(
                        _emit(
                            arg_e,
                            global_slots,
                            cur,
                            funcs,
                            param_scope,
                            func_param_sig,
                            param_slot_addr,
                        )
                    )
                    cur = pc0 + len(out)
                    out.append(pack_word(Opcode.STORE, 0))
                    cur = pc0 + len(out)
                out.append(pack_word(Opcode.CALL, funcs[head.name]))
                return out
            raise CodegenError(f"Неизвестная форма: ({head.name} …)")


def _compile_with_defuns(defuns: tuple[SList, ...], mains: tuple[Expr, ...]) -> list[int]:
    all_forms = tuple(defuns) + mains
    global_slots, param_slot_addr = _collect_bindings(all_forms)

    func_param_sig: dict[str, tuple[str, ...]] = {}
    for d in defuns:
        fn, ps, _ = _parse_defun_full(d)
        func_param_sig[fn] = ps

    words: list[int] = []
    jmp_ix = 0
    words.append(pack_word(Opcode.JMP, 0))

    func_targets: dict[str, int] = {}
    seen_names: set[str] = set()

    for d in defuns:
        name, params, body = _parse_defun_full(d)
        if name in seen_names:
            raise CodegenError(f"Повторное определение функции «{name}»")
        seen_names.add(name)
        start_pc = len(words)
        func_targets[name] = start_pc
        param_scope = {p: param_slot_addr[name, p] for p in params}
        words.extend(
            _emit(
                body,
                global_slots,
                start_pc,
                func_targets,
                param_scope,
                func_param_sig,
                param_slot_addr,
            )
        )
        words.append(pack_word(Opcode.SWAP, 0))
        words.append(pack_word(Opcode.RET, 0))

    main_start = len(words)
    words[jmp_ix] = pack_word(Opcode.JMP, main_start)

    main_expr = mains[0] if len(mains) == 1 else SList((Symbol("progn"),) + mains)
    words.extend(
        _emit(
            main_expr,
            global_slots,
            main_start,
            func_targets,
            None,
            func_param_sig,
            param_slot_addr,
        )
    )
    words.append(pack_word(Opcode.HALT, 0))
    return words


def compile_program(expr: Expr) -> list[int]:
    """Одно выражение-программа: код и завершающий HALT."""
    global_slots, _ = _collect_bindings((expr,))
    return _emit(expr, global_slots, 0, None, None, None, None) + [pack_word(Opcode.HALT, 0)]


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
    global_slots, _ = _collect_bindings(forms)
    return _emit(wrapped, global_slots, 0, None, None, None, None) + [pack_word(Opcode.HALT, 0)]
