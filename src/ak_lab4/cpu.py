"""CPU: PC/SP, такты, опкоды v0"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import TextIO

from ak_lab4.io_schedule import IrqScheduleEvent
from ak_lab4.isa import (
    NUM_IRQ_LINES,
    OPERAND_MASK,
    Opcode,
    Port,
    sign_extend_operand_i,
    unpack_word,
)
from ak_lab4.memory import DM_SIZE_WORDS, IM_SIZE_WORDS, STACK_BASE


class CpuFault(RuntimeError):
    """Сбой исполнения (стек, PC, деление на 0, …)"""


# Такты на команду
_TICKS: dict[int, int] = {
    int(Opcode.NOP): 1,
    int(Opcode.PUSH_IMM): 2,
    int(Opcode.DUP): 2,
    int(Opcode.DROP): 2,
    int(Opcode.LOAD): 4,
    int(Opcode.STORE): 4,
    int(Opcode.SWAP): 2,
    int(Opcode.ADD): 3,
    int(Opcode.SUB): 3,
    int(Opcode.MUL): 5,
    int(Opcode.DIV): 6,
    int(Opcode.MOD): 6,
    int(Opcode.EQ): 3,
    int(Opcode.SLT): 3,
    int(Opcode.JMP): 2,
    int(Opcode.JZ): 4,
    int(Opcode.CALL): 4,
    int(Opcode.RET): 3,
    int(Opcode.IN): 3,
    int(Opcode.OUT): 3,
    int(Opcode.HALT): 1,
    int(Opcode.EI): 1,
    int(Opcode.CLI): 1,
}

_SHADOW_STORE_CAPACITY = 2
_PARALLEL_FLUSH_TICKS = 1


def _opcode_breaks_dual_issue(op: int) -> bool:
    """Вторая инструкция в паре не выдаётся вместе с ветвлением/остановом/портами IRQ."""
    return op in (
        int(Opcode.JMP),
        int(Opcode.JZ),
        int(Opcode.CALL),
        int(Opcode.RET),
        int(Opcode.HALT),
        int(Opcode.EI),
        int(Opcode.CLI),
        int(Opcode.IN),
        int(Opcode.OUT),
    )


def can_dual_issue(op0: int, op1: int) -> bool:
    """
    Консервативная проверка независимости пары.
    Разрешаем пары без конфликтов по стеку и без операций управления/портов.
    """
    if _opcode_breaks_dual_issue(op0) or _opcode_breaks_dual_issue(op1):
        return False

    n0 = int(Opcode.NOP)
    n1 = int(Opcode.PUSH_IMM)
    d = int(Opcode.DUP)
    dr = int(Opcode.DROP)
    ld = int(Opcode.LOAD)
    st = int(Opcode.STORE)
    sw = int(Opcode.SWAP)
    allowed_pairs = {
        (n0, n0),
        (n0, n1),
        (n1, n0),
        (n1, n1),
        (d, n0),
        (n0, d),
        (dr, n0),
        (n0, dr),
        (ld, n0),
        (n0, ld),
        (st, n0),
        (n0, st),
        (sw, n0),
        (n0, sw),
    }
    return (op0, op1) in allowed_pairs


@dataclass
class Cpu:
    """Гарвард: IM/DM, адрес словами"""

    im: list[int] = field(default_factory=lambda: [0] * IM_SIZE_WORDS)
    dm: list[int] = field(default_factory=lambda: [0] * DM_SIZE_WORDS)
    pc: int = 0
    sp: int = STACK_BASE
    ticks: int = 0
    halted: bool = False

    # True: за один step — до двух последовательных инструкций (при отсутствии конфликтов).
    # По умолчанию выключено — golden и старые тесты без изменений.
    superscalar: bool = False

    # DATA_IN: очередь байт слева; пусто → на стек −1 (EOF)
    input_queue: deque[int] = field(default_factory=deque)

    # DATA_OUT: байты из младшего октета слова
    out_bytes: list[int] = field(default_factory=list)

    # trap по тактам
    irq_schedule: tuple[IrqScheduleEvent, ...] = field(default_factory=tuple)
    _schedule_i: int = field(default=0, repr=False)

    # последнее значение на линии irq (после события)
    irq_latches: dict[int, int] = field(default_factory=dict)

    # запрос по линии + байт на линии (не stdin)
    irq_pending: list[bool] = field(default_factory=lambda: [False] * NUM_IRQ_LINES)
    irq_line_value: list[int] = field(default_factory=lambda: [0] * NUM_IRQ_LINES)
    irq_enabled: bool = True
    interrupt_depth: int = 0

    # байт для первого IN в ISR после доставки IRQ
    _irq_delivered_byte: int | None = field(default=None, repr=False)
    # AC_SHADOW для stack-варианта в superscalar-режиме
    shadow_stores: list[tuple[int, int]] = field(default_factory=list, repr=False)
    last_load_addr: int | None = field(default=None, repr=False)
    last_load_value: int | None = field(default=None, repr=False)

    def _invalidate_last_load(self) -> None:
        self.last_load_addr = None
        self.last_load_value = None

    def _note_store_visibility(self, addr: int, value: int) -> None:
        """Обновить кэш последней загрузки после записи в память/теневую очередь."""
        if self.last_load_addr == addr:
            self.last_load_value = value & 0xFFFFFFFF

    def _read_from_dm_or_shadow(self, addr: int) -> int:
        for sh_addr, sh_val in reversed(self.shadow_stores):
            if sh_addr == addr:
                return sh_val & 0xFFFFFFFF
        return self.dm[addr] & 0xFFFFFFFF

    def _flush_shadow_stores(
        self,
        log: TextIO | None = None,
        *,
        reason: str,
    ) -> bool:
        if not self.shadow_stores:
            return False
        if log is not None:
            mode = "ISR" if self.interrupt_depth > 0 else "USR"
            payload = "\t".join(f"{a}:{v:08X}" for a, v in self.shadow_stores)
            log.write(f"{self.ticks}\tPAR_FLUSH\t{reason}\t{payload}\t{mode}\n")
        for addr, value in self.shadow_stores:
            a = self._ensure_dm_addr(addr)
            self.dm[a] = value & 0xFFFFFFFF
            self._note_store_visibility(a, value)
        self.shadow_stores.clear()
        self.ticks += _PARALLEL_FLUSH_TICKS
        return True

    def _apply_irq_schedule_for_current_ticks(self) -> None:
        """события расписания на текущий такт"""
        while self._schedule_i < len(self.irq_schedule):
            ev = self.irq_schedule[self._schedule_i]
            if ev.tick > self.ticks:
                break
            irq = ev.irq
            if 0 <= irq < NUM_IRQ_LINES:
                v = ev.value & 0xFF
                self.irq_line_value[irq] = v
                self.irq_latches[irq] = v
                self.irq_pending[irq] = True
            self._schedule_i += 1

    def _read_vector_target(self, irq: int) -> int:
        idx = 1 + irq
        if idx < 0 or idx >= IM_SIZE_WORDS:
            msg = f"вектор IRQ{irq}: слово @{idx} вне IM"
            raise CpuFault(msg)
        op_b, opnd = unpack_word(self.im[idx])
        if op_b != int(Opcode.JMP):
            msg = f"вектор IRQ{irq}: в IM[{idx}] должен быть jmp"
            raise CpuFault(msg)
        return self._ensure_im_pc(opnd & OPERAND_MASK)

    def _read_port_in(self, port: int) -> int:
        """чтение IN по номеру порта"""
        if port == int(Port.DATA_IN):
            if self._irq_delivered_byte is not None:
                b = self._irq_delivered_byte & 0xFF
                self._irq_delivered_byte = None
                return b
            if self.input_queue:
                return self.input_queue.popleft() & 0xFF
            return -1
        if port == int(Port.IRQ_STATUS):
            return ((self.interrupt_depth & 0xFF) << 8) | (1 if self.irq_enabled else 0)
        return 0

    def _ensure_dm_addr(self, addr: int) -> int:
        if addr < 0 or addr >= DM_SIZE_WORDS:
            msg = f"DM: адрес {addr} мимо диапазона"
            raise CpuFault(msg)
        return addr

    def _ensure_im_pc(self, addr: int) -> int:
        if addr < 0 or addr >= IM_SIZE_WORDS:
            msg = f"PC {addr} вне IM"
            raise CpuFault(msg)
        return addr

    def _push(self, value: int) -> None:
        v = value & 0xFFFFFFFF
        if self.sp >= DM_SIZE_WORDS:
            msg = "стек переполнен"
            raise CpuFault(msg)
        a = self._ensure_dm_addr(self.sp)
        self.dm[a] = v
        self.sp += 1

    def _pop(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "pop из пустого стека"
            raise CpuFault(msg)
        self.sp -= 1
        a = self._ensure_dm_addr(self.sp)
        return self.dm[a] & 0xFFFFFFFF

    def _peek_top(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "dup при пустом стеке"
            raise CpuFault(msg)
        a = self._ensure_dm_addr(self.sp - 1)
        return self.dm[a] & 0xFFFFFFFF

    def _add_ticks(self, op: int) -> None:
        self.ticks += _TICKS.get(op, 1)

    def _dispatch_opcode(
        self,
        insn_pc: int,
        op_byte: int,
        operand: int,
        log: TextIO | None = None,
    ) -> None:
        """Исполнить одну инструкцию с адреса insn_pc (next_pc = insn_pc+1 для линейного потока)."""
        next_pc = insn_pc + 1
        op = op_byte

        match op:
            case x if x == Opcode.NOP:
                self.pc = next_pc
            case x if x == Opcode.PUSH_IMM:
                imm = sign_extend_operand_i(operand) & 0xFFFFFFFF
                self._push(imm)
                self.pc = next_pc
            case x if x == Opcode.DUP:
                self._push(self._peek_top())
                self.pc = next_pc
            case x if x == Opcode.DROP:
                _ = self._pop()
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.LOAD:
                addr = self._pop()
                a = self._ensure_dm_addr(addr)
                if (
                    self.superscalar
                    and self.last_load_addr == a
                    and self.last_load_value is not None
                ):
                    val = self.last_load_value & 0xFFFFFFFF
                else:
                    val = (
                        self._read_from_dm_or_shadow(a)
                        if self.superscalar
                        else (self.dm[a] & 0xFFFFFFFF)
                    )
                self._push(val)
                if self.superscalar:
                    self.last_load_addr = a
                    self.last_load_value = val
                self.pc = next_pc
            case x if x == Opcode.STORE:
                val = self._pop()
                addr = self._pop()
                a = self._ensure_dm_addr(addr)
                v = val & 0xFFFFFFFF
                if self.superscalar:
                    if len(self.shadow_stores) >= _SHADOW_STORE_CAPACITY:
                        self._flush_shadow_stores(log, reason="overflow")
                    self.shadow_stores.append((a, v))
                    self._note_store_visibility(a, v)
                else:
                    self.dm[a] = v
                self.pc = next_pc
            case x if x == Opcode.SWAP:
                top = self._pop()
                below = self._pop()
                self._push(top)
                self._push(below)
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.ADD:
                x1 = self._pop()
                y = self._pop()
                self._push((y + x1) & 0xFFFFFFFF)
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.SUB:
                x1 = self._pop()
                y = self._pop()
                self._push((y - x1) & 0xFFFFFFFF)
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.MUL:
                x1 = self._pop()
                y = self._pop()
                prod = _signed32(y) * _signed32(x1)
                self._push(_unsigned32(prod))
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.DIV:
                x1 = self._pop()
                y = self._pop()
                if x1 == 0:
                    raise CpuFault("деление на 0")
                q = math.trunc(_signed32(y) / _signed32(x1))
                self._push(_unsigned32(q))
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.MOD:
                x1 = self._pop()
                y = self._pop()
                if x1 == 0:
                    raise CpuFault("mod и делитель 0")
                yi, xi = _signed32(y), _signed32(x1)
                r = yi - math.trunc(yi / xi) * xi
                self._push(_unsigned32(r))
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.EQ:
                x1 = self._pop()
                y = self._pop()
                self._push(1 if (y & 0xFFFFFFFF) == (x1 & 0xFFFFFFFF) else 0)
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.SLT:
                b = self._pop()
                a = self._pop()
                self._push(
                    1 if _signed32(a & 0xFFFFFFFF) < _signed32(b & 0xFFFFFFFF) else 0,
                )
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.JMP:
                target = operand & OPERAND_MASK
                self.pc = self._ensure_im_pc(target)
            case x if x == Opcode.JZ:
                cond = self._pop()
                target = operand & OPERAND_MASK
                if (cond & 0xFFFFFFFF) == 0:
                    self.pc = self._ensure_im_pc(target)
                else:
                    self.pc = next_pc
                self._invalidate_last_load()
            case x if x == Opcode.CALL:
                target = operand & OPERAND_MASK
                self._push(next_pc & 0xFFFFFFFF)
                self._invalidate_last_load()
                self.pc = self._ensure_im_pc(target)
            case x if x == Opcode.RET:
                addr = self._pop()
                if self.interrupt_depth > 0:
                    self.interrupt_depth -= 1
                self._invalidate_last_load()
                self.pc = self._ensure_im_pc(addr & 0xFFFFFFFF)
            case x if x == Opcode.IN:
                port = operand & 0xFFFF
                if (operand >> 16) & 0xFF != 0:
                    pass  # резерв в v0 не трогаем
                val = self._read_port_in(port)
                self._push(_unsigned32(val))
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.OUT:
                val = self._pop()
                port = operand & 0xFFFF
                if port == int(Port.DATA_OUT):
                    self.out_bytes.append(val & 0xFF)
                elif port == int(Port.IRQ_STATUS):
                    self.irq_enabled = (val & 0xFFFFFFFF) != 0
                elif port == int(Port.IRQ_EOI):
                    pass
                self._invalidate_last_load()
                self.pc = next_pc
            case x if x == Opcode.EI:
                self.irq_enabled = True
                self.pc = next_pc
            case x if x == Opcode.CLI:
                self.irq_enabled = False
                self.pc = next_pc
            case x if x == Opcode.HALT:
                if self.superscalar:
                    self._flush_shadow_stores(log, reason="halt")
                self.halted = True
                self.pc = next_pc
            case _:
                word = self.im[insn_pc] & 0xFFFFFFFF
                msg = f"неизвестный опкод 0x{op_byte:02X} @PC={insn_pc} word={word:08X}"
                raise CpuFault(msg)

    def _step_scalar(self, log: TextIO | None) -> None:
        """Одна инструкция по PC (классическое поведение)."""
        pc0 = self._ensure_im_pc(self.pc)
        word = self.im[pc0] & 0xFFFFFFFF
        op_byte, operand = unpack_word(word)

        if log is not None:
            mode = "ISR" if self.interrupt_depth > 0 else "USR"
            log.write(f"{self.ticks}\t{pc0}\t{word:08X}\t{mode}\n")

        self._dispatch_opcode(pc0, op_byte, operand, log)
        self._add_ticks(op_byte)
        if not self.halted:
            self._try_deliver_irq_after_instruction(log)

    def _step_superscalar(self, log: TextIO | None) -> None:
        """До двух последовательных инструкций за один step при отсутствии конфликтов."""
        if self.interrupt_depth > 0:
            self._step_scalar(log)
            return

        pc0 = self._ensure_im_pc(self.pc)
        word0 = self.im[pc0] & 0xFFFFFFFF
        op0, od0 = unpack_word(word0)

        if _opcode_breaks_dual_issue(op0):
            self._step_scalar(log)
            return

        pc1 = pc0 + 1
        if pc1 >= IM_SIZE_WORDS:
            self._step_scalar(log)
            return

        word1 = self.im[pc1] & 0xFFFFFFFF
        op1, od1 = unpack_word(word1)

        if _opcode_breaks_dual_issue(op1):
            self._step_scalar(log)
            return

        if not can_dual_issue(op0, op1):
            self._step_scalar(log)
            return

        if log is not None:
            mode = "ISR" if self.interrupt_depth > 0 else "USR"
            log.write(
                f"{self.ticks}\tPAR\t{pc0}\t{word0:08X}\t{pc1}\t{word1:08X}\t{mode}\n",
            )

        self._dispatch_opcode(pc0, op0, od0, log)
        if self.halted:
            self._add_ticks(op0)
            return

        self._dispatch_opcode(pc1, op1, od1, log)
        tick0 = _TICKS.get(op0, 1)
        tick1 = _TICKS.get(op1, 1)
        self.ticks += tick0 if tick0 > tick1 else tick1

        if not self.halted:
            self._try_deliver_irq_after_instruction(log)

    def step(self, log: TextIO | None = None) -> None:
        """одна «порция» исполнения: скаляр — одна инструкция; superscalar — до двух."""
        if self.halted:
            return

        self._apply_irq_schedule_for_current_ticks()

        if not self.superscalar:
            self._step_scalar(log)
        else:
            self._step_superscalar(log)

    def _try_deliver_irq_after_instruction(self, log: TextIO | None = None) -> None:
        """после инструкции: один pending IRQ → push return PC, jmp на вектор"""
        if self.ticks == 0:
            return
        if not self.irq_enabled:
            return
        if self.interrupt_depth > 0:
            return
        for irq in range(NUM_IRQ_LINES):
            if not self.irq_pending[irq]:
                continue
            if self.superscalar:
                self._flush_shadow_stores(log, reason="irq")
            ret_pc = self.pc
            self._push(ret_pc & 0xFFFFFFFF)
            self.pc = self._read_vector_target(irq)
            self.interrupt_depth += 1
            self._irq_delivered_byte = self.irq_line_value[irq] & 0xFF
            self.irq_pending[irq] = False
            return


def _signed32(u: int) -> int:
    u &= 0xFFFFFFFF
    return u - 0x100000000 if u >= 0x80000000 else u


def _unsigned32(i: int) -> int:
    return i & 0xFFFFFFFF


def init_memory_from_segments(
    code_words: list[int],
    data_words: list[int],
) -> tuple[list[int], list[int]]:
    """залить IM с PC=0 и DM с адреса 0"""
    im = [0] * IM_SIZE_WORDS
    dm = [0] * DM_SIZE_WORDS
    for i, w in enumerate(code_words):
        if i >= IM_SIZE_WORDS:
            msg = "сегмент кода не влезает в IM"
            raise CpuFault(msg)
        im[i] = w & 0xFFFFFFFF
    for i, w in enumerate(data_words):
        if i >= DM_SIZE_WORDS:
            msg = "сегмент данных не влезает в DM"
            raise CpuFault(msg)
        dm[i] = w & 0xFFFFFFFF
    return im, dm


def run_program(
    cpu: Cpu,
    *,
    max_ticks: int,
    log: TextIO | None = None,
) -> None:
    """крутить step до halt/fault/лимита тактов"""
    while not cpu.halted:
        if cpu.ticks >= max_ticks:
            msg = f"лимит тактов ({max_ticks})"
            raise CpuFault(msg)
        cpu.step(log=log)
