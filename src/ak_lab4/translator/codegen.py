"""Генерация машинных слов: arith, setq, if, eq, progn, in/out (порты), defun, CALL"""

from __future__ import annotations

from dataclasses import dataclass

from ak_lab4.isa import NUM_IRQ_LINES, Opcode, Port, pack_word
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
    """Неподдерживаемая конструкция или неверная арность"""


@dataclass
class CompiledProgram:
    """Гарвард: IM для кода, DM для pstr и слотов переменных"""

    code: list[int]
    data: list[int]


def _check_imm24(v: int) -> int:
    if v < IMM24_MIN or v > IMM24_MAX:
        msg = f"число {v} вне 24-бит signed ({IMM24_MIN}…{IMM24_MAX})"
        raise CodegenError(msg)
    return v


def _collect_bindings(
    forms: tuple[Expr, ...],
    *,
    slot_base: int = 0,
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """глобальные setq и слоты (fname, pname) → адрес в DM"""

    order_setq: list[str] = []

    def walk(ex: Expr) -> None:
        match ex:
            case SList(items):
                if len(items) >= 4 and isinstance(items[0], Symbol) and items[0].name == "defun":
                    for b in items[3:]:
                        walk(b)
                if (
                    len(items) >= 3
                    and isinstance(items[0], Symbol)
                    and items[0].name == "setq"
                    and isinstance(items[1], Symbol)
                ):
                    order_setq.append(items[1].name)
                if (
                    len(items) >= 3
                    and isinstance(items[0], Symbol)
                    and items[0].name == "interrupt"
                ):
                    for b in items[2:]:
                        walk(b)
                for it in items:
                    walk(it)
            case _:
                pass

    for f in forms:
        walk(f)

    global_slots: dict[str, int] = {}
    nxt = slot_base
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
                    raise CodegenError(f"defun «{fname}»: параметр «{p}» уже есть")
                param_slot[key] = nxt
                nxt += 1

    return global_slots, param_slot


def _walk_collect_str_literals(e: Expr, seen: set[str], ordered: list[str]) -> None:
    """первые вхождения уникальных строк по порядку обхода"""
    match e:
        case StrLit(s):
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        case SList(items):
            for it in items:
                _walk_collect_str_literals(it, seen, ordered)
        case _:
            pass


def _ordered_unique_strings_from_forms(forms: tuple[Expr, ...]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for f in forms:
        _walk_collect_str_literals(f, seen, ordered)
    return ordered


def _layout_pstr(strings: list[str]) -> tuple[list[int], dict[str, int]]:
    """слова [len][ord…]; база строки — адрес слова длины"""
    data: list[int] = []
    addr: dict[str, int] = {}
    for s in strings:
        if len(s) > IMM24_MAX:
            msg = f"строка длиннее {IMM24_MAX} символов — так не разложить в память"
            raise CodegenError(msg)
        base = len(data)
        addr[s] = base
        data.append(len(s) & 0xFFFFFFFF)
        for ch in s:
            o = ord(ch)
            if o > 0xFFFFFFFF:
                raise CodegenError("символ не помещается в одно машинное слово")
            data.append(o & 0xFFFFFFFF)
    return data, addr


def _slot_addr(
    name: str,
    global_slots: dict[str, int],
    param_scope: dict[str, int] | None,
) -> int:
    if param_scope is not None and name in param_scope:
        return param_scope[name]
    if name in global_slots:
        return global_slots[name]
    raise CodegenError(f"нет переменной «{name}»")


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
    if len(d.items) < 4:
        raise CodegenError(
            "defun: нужно (defun имя (параметры) тело …)",
        )
    _kw, name_el, params_el, *body_forms = d.items
    if not isinstance(name_el, Symbol):
        raise CodegenError("defun: имя должно быть символом")
    if not isinstance(params_el, SList):
        raise CodegenError("defun: параметры — список в скобках")
    params: list[str] = []
    for item in params_el.items:
        if not isinstance(item, Symbol):
            raise CodegenError("defun: каждый параметр — отдельный символ")
        params.append(item.name)
    if len(set(params)) != len(params):
        raise CodegenError("defun: имена параметров не должны повторяться")
    if len(body_forms) == 1:
        body: Expr = body_forms[0]
    else:
        body = SList((Symbol("progn"),) + tuple(body_forms))
    return name_el.name, tuple(params), body


def _is_interrupt_form(e: Expr) -> bool:
    return (
        isinstance(e, SList)
        and len(e.items) >= 3
        and isinstance(e.items[0], Symbol)
        and e.items[0].name == "interrupt"
    )


def _parse_interrupt_form(e: SList) -> tuple[int, Expr]:
    _kw, irq_el, *rest = e.items
    if not isinstance(irq_el, IntLit):
        raise CodegenError("interrupt: второй аргумент — номер линии (целое)")
    irq = irq_el.value
    if irq < 0 or irq >= NUM_IRQ_LINES:
        raise CodegenError(f"interrupt: линия только 0…{NUM_IRQ_LINES - 1}")
    if not rest:
        raise CodegenError("interrupt: нужно тело после номера линии")
    if len(rest) == 1:
        body: Expr = rest[0]
    else:
        body = SList((Symbol("progn"),) + tuple(rest))
    return irq, body


def _split_trailing_interrupts(
    mains: tuple[Expr, ...],
) -> tuple[tuple[Expr, ...], tuple[SList, ...]]:
    lst = list(mains)
    intr: list[SList] = []
    while lst and _is_interrupt_form(lst[-1]):
        last = lst.pop()
        assert isinstance(last, SList)
        intr.append(last)
    intr.reverse()
    return tuple(lst), tuple(intr)


def _split_defuns_first(forms: tuple[Expr, ...]) -> tuple[tuple[SList, ...], tuple[Expr, ...]]:
    defuns: list[SList] = []
    mains: list[Expr] = []
    stage = "def"
    for f in forms:
        if _is_defun_form(f):
            if stage == "main":
                raise CodegenError("сначала все defun, потом основной код")
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
    string_addrs: dict[str, int] | None,
) -> list[int]:
    if len(args) < 2:
        raise CodegenError(f"«{name}»: нужно минимум два аргумента")
    ctx = (funcs, param_scope, func_param_sig, param_slot_addr, string_addrs)
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
    string_addrs: dict[str, int] | None = None,
) -> list[int]:
    """вызовы с аргументами — нужны func_param_sig и param_slot_addr"""

    match e:
        case IntLit(v):
            v2 = _check_imm24(v)
            return [pack_word(Opcode.PUSH_IMM, v2)]
        case StrLit(s):
            if string_addrs is None or s not in string_addrs:
                raise CodegenError("строка не из пула (баг компилятора)")
            base = string_addrs[s]
            return [pack_word(Opcode.PUSH_IMM, _check_imm24(base))]
        case Symbol(name):
            addr = _slot_addr(name, global_slots, param_scope)
            return [
                pack_word(Opcode.PUSH_IMM, _check_imm24(addr)),
                pack_word(Opcode.LOAD, 0),
            ]
        case SList(items):
            if not items:
                raise CodegenError("пустой список () нельзя как выражение")
            head, *args = items
            if not isinstance(head, Symbol):
                raise CodegenError("вызов: слева должен быть символ")
            if head.name == "drop":
                if args:
                    raise CodegenError("у drop не бывает аргументов")
                return [pack_word(Opcode.DROP, 0)]
            if head.name == "nop":
                if args:
                    raise CodegenError("у nop не бывает аргументов")
                return [pack_word(Opcode.NOP, 0)]
            if head.name == "progn":
                if not args:
                    raise CodegenError("progn: хотя бы одна форма внутри")
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
                        string_addrs,
                    )
                    parts.extend(segment)
                    cur = pc0 + len(parts)
                    if i < len(args) - 1:
                        parts.append(pack_word(Opcode.DROP, 0))
                        cur = pc0 + len(parts)
                return parts
            if head.name == "ei":
                if args:
                    raise CodegenError("ei без аргументов")
                return [pack_word(Opcode.EI, 0)]
            if head.name == "di":
                if args:
                    raise CodegenError("di без аргументов")
                return [pack_word(Opcode.CLI, 0)]
            if head.name == "in":
                if args:
                    raise CodegenError("in без аргументов")
                return [pack_word(Opcode.IN, int(Port.DATA_IN))]
            if head.name == "out":
                if len(args) != 1:
                    raise CodegenError("out: один аргумент — значение для порта")
                val_c = _emit(
                    args[0],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                return val_c + [
                    pack_word(Opcode.DUP, 0),
                    pack_word(Opcode.OUT, int(Port.DATA_OUT)),
                ]
            if head.name == "load":
                if len(args) != 1:
                    raise CodegenError("load: один аргумент — адрес слова в DM")
                addr_c = _emit(
                    args[0],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                return addr_c + [pack_word(Opcode.LOAD, 0)]
            if head.name == "store":
                if len(args) != 2:
                    raise CodegenError("store: адрес и значение")
                addr_c = _emit(
                    args[0],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                val_c = _emit(
                    args[1],
                    global_slots,
                    pc0 + len(addr_c),
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                return (
                    addr_c
                    + val_c
                    + [
                        pack_word(Opcode.STORE, 0),
                        pack_word(Opcode.PUSH_IMM, 0),
                    ]
                )
            if head.name == "setq":
                if len(args) != 2:
                    raise CodegenError("setq: два аргумента — имя и выражение")
                sym_el, rhs = args
                if not isinstance(sym_el, Symbol):
                    raise CodegenError("setq: первым должно быть имя (символ)")
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
                        string_addrs,
                    )
                    + [
                        pack_word(Opcode.STORE, 0),
                        pack_word(Opcode.PUSH_IMM, _check_imm24(addr)),
                        pack_word(Opcode.LOAD, 0),
                    ]
                )
            if head.name == "if":
                if len(args) != 3:
                    raise CodegenError("if: три аргумента — условие, then, else")
                pred_e, then_e, else_e = args
                pred_c = _emit(
                    pred_e,
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
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
                    string_addrs,
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
                    string_addrs,
                )
                end_pc = else_start + len(else_c)
                return (
                    pred_c
                    + [pack_word(Opcode.JZ, else_start)]
                    + then_c
                    + [pack_word(Opcode.JMP, end_pc)]
                    + else_c
                )
            if head.name == "<":
                if len(args) != 2:
                    raise CodegenError("< — ровно два аргумента")
                left = _emit(
                    args[0],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                right = _emit(
                    args[1],
                    global_slots,
                    pc0 + len(left),
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                return left + right + [pack_word(Opcode.SLT, 0)]
            if head.name == ">":
                if len(args) != 2:
                    raise CodegenError("> — ровно два аргумента")
                bl = _emit(
                    args[1],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                ar = _emit(
                    args[0],
                    global_slots,
                    pc0 + len(bl),
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                return bl + ar + [pack_word(Opcode.SLT, 0)]
            if head.name in ("eq", "="):
                if len(args) != 2:
                    raise CodegenError("eq / = — ровно два аргумента")
                left = _emit(
                    args[0],
                    global_slots,
                    pc0,
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
                )
                right = _emit(
                    args[1],
                    global_slots,
                    pc0 + len(left),
                    funcs,
                    param_scope,
                    func_param_sig,
                    param_slot_addr,
                    string_addrs,
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
                    string_addrs,
                )
            if funcs is not None and head.name in funcs:
                if func_param_sig is None or param_slot_addr is None:
                    raise CodegenError("внутри компилятора: нет таблицы параметров для CALL")
                sig = func_param_sig[head.name]
                if len(args) != len(sig):
                    raise CodegenError(
                        f"«{head.name}»: нужно {len(sig)} аргументов, передано {len(args)}",
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
                            string_addrs,
                        )
                    )
                    cur = pc0 + len(out)
                    out.append(pack_word(Opcode.STORE, 0))
                    cur = pc0 + len(out)
                out.append(pack_word(Opcode.CALL, funcs[head.name]))
                return out
            raise CodegenError(f"не знаю форму ({head.name} …)")


def _compile_with_defuns(
    defuns: tuple[SList, ...],
    mains: tuple[Expr, ...],
    *,
    slot_base: int,
    string_addrs: dict[str, int],
) -> list[int]:
    """Два прохода: сначала длины тел (CALL с фиктивным 0), затем раскладка и эмит с реальными PC.

    Так вызовы функций, объявленных ниже в файле, получают правильный адрес, и if/jz/jmp
    используют итоговый start_pc функции.
    """
    all_forms = tuple(defuns) + mains
    global_slots, param_slot_addr = _collect_bindings(all_forms, slot_base=slot_base)

    ordered: list[tuple[str, Expr]] = []
    seen_names: set[str] = set()
    func_param_sig: dict[str, tuple[str, ...]] = {}
    for d in defuns:
        name, params, body = _parse_defun_full(d)
        if name in seen_names:
            raise CodegenError(f"функция «{name}» уже объявлена")
        seen_names.add(name)
        func_param_sig[name] = params
        ordered.append((name, body))

    names = [n for n, _ in ordered]
    dummy_targets: dict[str, int] = {n: 0 for n in names}

    lens: dict[str, int] = {}
    for name, body in ordered:
        param_scope = {p: param_slot_addr[name, p] for p in func_param_sig[name]}
        chunk = _emit(
            body,
            global_slots,
            0,
            dummy_targets,
            param_scope,
            func_param_sig,
            param_slot_addr,
            string_addrs,
        )
        lens[name] = len(chunk)

    starts: dict[str, int] = {}
    pos = 1
    for name, _ in ordered:
        starts[name] = pos
        pos += lens[name] + 2

    main_start = pos
    full_targets: dict[str, int] = {n: starts[n] for n in names}

    words: list[int] = [pack_word(Opcode.JMP, 0)]
    for name, body in ordered:
        start_pc = starts[name]
        param_scope = {p: param_slot_addr[name, p] for p in func_param_sig[name]}
        words.extend(
            _emit(
                body,
                global_slots,
                start_pc,
                full_targets,
                param_scope,
                func_param_sig,
                param_slot_addr,
                string_addrs,
            )
        )
        words.append(pack_word(Opcode.SWAP, 0))
        words.append(pack_word(Opcode.RET, 0))

    words[0] = pack_word(Opcode.JMP, main_start)

    main_expr = mains[0] if len(mains) == 1 else SList((Symbol("progn"),) + mains)
    words.extend(
        _emit(
            main_expr,
            global_slots,
            main_start,
            full_targets,
            None,
            func_param_sig,
            param_slot_addr,
            string_addrs,
        )
    )
    words.append(pack_word(Opcode.HALT, 0))
    return words


def _handler_needs_drop_before_ret(body: Expr) -> bool:
    """если последняя форма ISR что-то положила на стек — перед RET нужен DROP"""

    def last_form(ex: Expr) -> Expr:
        if isinstance(ex, SList) and ex.items:
            head = ex.items[0]
            if isinstance(head, Symbol) and head.name == "progn" and len(ex.items) >= 2:
                return last_form(ex.items[-1])
        return ex

    lf = last_form(body)
    if isinstance(lf, StrLit):
        return True
    if isinstance(lf, SList) and lf.items:
        h = lf.items[0]
        if isinstance(h, Symbol) and h.name in (
            "in",
            "+",
            "-",
            "*",
            "/",
            "mod",
            "eq",
            "=",
            "<",
            ">",
            "load",
            "store",
            "setq",
        ):
            return True
    return False


def _compile_with_defuns_interrupts(
    defuns: tuple[SList, ...],
    mains: tuple[Expr, ...],
    irq_handlers: dict[int, Expr],
    *,
    slot_base: int,
    string_addrs: dict[str, int],
) -> list[int]:
    """как _compile_with_defuns, плюс IM[1..N]=jmp на handler; после HALT — ISR и RET"""
    irq_vals = tuple(irq_handlers.values())
    all_forms = tuple(defuns) + mains + irq_vals
    global_slots, param_slot_addr = _collect_bindings(all_forms, slot_base=slot_base)

    ordered: list[tuple[str, Expr]] = []
    seen_names: set[str] = set()
    func_param_sig: dict[str, tuple[str, ...]] = {}
    for d in defuns:
        name, params, body = _parse_defun_full(d)
        if name in seen_names:
            raise CodegenError(f"функция «{name}» уже объявлена")
        seen_names.add(name)
        func_param_sig[name] = params
        ordered.append((name, body))

    names = [n for n, _ in ordered]
    dummy_targets: dict[str, int] = {n: 0 for n in names}

    lens: dict[str, int] = {}
    for name, body in ordered:
        param_scope = {p: param_slot_addr[name, p] for p in func_param_sig[name]}
        chunk = _emit(
            body,
            global_slots,
            0,
            dummy_targets,
            param_scope,
            func_param_sig,
            param_slot_addr,
            string_addrs,
        )
        lens[name] = len(chunk)

    header_slots = 1 + NUM_IRQ_LINES
    starts: dict[str, int] = {}
    pos = header_slots
    for name, _ in ordered:
        starts[name] = pos
        pos += lens[name] + 2

    main_start = pos
    full_targets: dict[str, int] = {n: starts[n] for n in names}

    words: list[int] = [pack_word(Opcode.JMP, 0)] + [pack_word(Opcode.JMP, 0)] * NUM_IRQ_LINES
    for name, body in ordered:
        start_pc = starts[name]
        param_scope = {p: param_slot_addr[name, p] for p in func_param_sig[name]}
        words.extend(
            _emit(
                body,
                global_slots,
                start_pc,
                full_targets,
                param_scope,
                func_param_sig,
                param_slot_addr,
                string_addrs,
            )
        )
        words.append(pack_word(Opcode.SWAP, 0))
        words.append(pack_word(Opcode.RET, 0))

    words[0] = pack_word(Opcode.JMP, main_start)

    main_expr = mains[0] if len(mains) == 1 else SList((Symbol("progn"),) + mains)
    words.extend(
        _emit(
            main_expr,
            global_slots,
            main_start,
            full_targets,
            None,
            func_param_sig,
            param_slot_addr,
            string_addrs,
        )
    )
    words.append(pack_word(Opcode.HALT, 0))

    handler_pc: dict[int, int] = {}
    for irq in sorted(irq_handlers.keys()):
        entry = len(words)
        handler_pc[irq] = entry
        hbody = irq_handlers[irq]
        extra: list[int] = []
        if _handler_needs_drop_before_ret(hbody):
            extra.append(pack_word(Opcode.DROP, 0))
        words.extend(
            _emit(
                hbody,
                global_slots,
                entry,
                full_targets,
                None,
                func_param_sig,
                param_slot_addr,
                string_addrs,
            )
            + extra
            + [pack_word(Opcode.RET, 0)]
        )

    for irq, tgt in handler_pc.items():
        words[1 + irq] = pack_word(Opcode.JMP, tgt)

    return words


def _compile_mains_interrupts(
    mains: tuple[Expr, ...],
    irq_handlers: dict[int, Expr],
    *,
    slot_base: int,
    string_addrs: dict[str, int],
) -> list[int]:
    irq_vals = tuple(irq_handlers.values())
    all_forms = tuple(mains) + irq_vals
    global_slots, _ = _collect_bindings(all_forms, slot_base=slot_base)
    header_slots = 1 + NUM_IRQ_LINES
    main_start = header_slots
    main_expr = mains[0] if len(mains) == 1 else SList((Symbol("progn"),) + mains)

    words: list[int] = [pack_word(Opcode.JMP, 0)] + [pack_word(Opcode.JMP, 0)] * NUM_IRQ_LINES
    words.extend(_emit(main_expr, global_slots, main_start, None, None, None, None, string_addrs))
    words.append(pack_word(Opcode.HALT, 0))
    words[0] = pack_word(Opcode.JMP, main_start)

    handler_pc: dict[int, int] = {}
    for irq in sorted(irq_handlers.keys()):
        entry = len(words)
        handler_pc[irq] = entry
        hbody = irq_handlers[irq]
        extra = [pack_word(Opcode.DROP, 0)] if _handler_needs_drop_before_ret(hbody) else []
        words.extend(
            _emit(hbody, global_slots, entry, None, None, None, None, string_addrs)
            + extra
            + [pack_word(Opcode.RET, 0)]
        )
    for irq, tgt in handler_pc.items():
        words[1 + irq] = pack_word(Opcode.JMP, tgt)
    return words


def compile_program(expr: Expr) -> CompiledProgram:
    """одна верхнеуровневая форма — код, pstr в DM, HALT в конце"""
    strings = _ordered_unique_strings_from_forms((expr,))
    data_words, str_addr = _layout_pstr(strings)
    slot_base = len(data_words)
    global_slots, _ = _collect_bindings((expr,), slot_base=slot_base)
    code = _emit(expr, global_slots, 0, None, None, None, None, str_addr) + [
        pack_word(Opcode.HALT, 0)
    ]
    return CompiledProgram(code=code, data=data_words)


def compile_forms(forms: tuple[Expr, ...]) -> CompiledProgram:
    """несколько форм, defun и опционально хвост (interrupt n …)"""
    if not forms:
        raise CodegenError("нечего компилировать — файл пустой")
    strings = _ordered_unique_strings_from_forms(forms)
    data_words, str_addr = _layout_pstr(strings)
    slot_base = len(data_words)

    defuns, mains_tail = _split_defuns_first(forms)
    mains_only, interrupt_forms = _split_trailing_interrupts(mains_tail)

    if interrupt_forms:
        irq_handlers: dict[int, Expr] = {}
        for form in interrupt_forms:
            assert isinstance(form, SList)
            irq, body = _parse_interrupt_form(form)
            if irq in irq_handlers:
                raise CodegenError(f"interrupt {irq} объявлен дважды")
            irq_handlers[irq] = body
        if defuns:
            if not mains_only:
                raise CodegenError("между defun и interrupt нужен основной код")
            code = _compile_with_defuns_interrupts(
                defuns,
                mains_only,
                irq_handlers,
                slot_base=slot_base,
                string_addrs=str_addr,
            )
            return CompiledProgram(code=code, data=data_words)
        if not mains_only:
            raise CodegenError("перед (interrupt …) должна быть основная программа")
        code = _compile_mains_interrupts(
            mains_only,
            irq_handlers,
            slot_base=slot_base,
            string_addrs=str_addr,
        )
        return CompiledProgram(code=code, data=data_words)

    if defuns:
        if not mains_only:
            raise CodegenError("после defun нужна хотя бы одна форма основного кода")
        code = _compile_with_defuns(
            defuns,
            mains_only,
            slot_base=slot_base,
            string_addrs=str_addr,
        )
        return CompiledProgram(code=code, data=data_words)
    if len(forms) == 1:
        return compile_program(forms[0])
    if len(mains_only) == 1:
        return compile_program(mains_only[0])
    wrapped = SList((Symbol("progn"),) + mains_only)
    global_slots, _ = _collect_bindings(mains_only, slot_base=slot_base)
    code = _emit(wrapped, global_slots, 0, None, None, None, None, str_addr) + [
        pack_word(Opcode.HALT, 0)
    ]
    return CompiledProgram(code=code, data=data_words)
