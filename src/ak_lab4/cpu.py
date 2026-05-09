"""Модель CPU: PC/SP, такты, исполнение по таблице opcodes v0."""

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
    """Ошибка исполнения (стек, PC, деление на ноль и т.д.)."""


# Такты на команду по docs/spec/03-isa-opcodes-v0.md
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


@dataclass
class Cpu:
    """Гарвард: отдельные банки IM/DM, словная адресация."""

    im: list[int] = field(default_factory=lambda: [0] * IM_SIZE_WORDS)
    dm: list[int] = field(default_factory=lambda: [0] * DM_SIZE_WORDS)
    pc: int = 0
    sp: int = STACK_BASE
    ticks: int = 0
    halted: bool = False
    # Ввод порта DATA_IN: байты снимаются слева; пустая очередь → на стек кладётся −1 (EOF).
    input_queue: deque[int] = field(default_factory=deque)
    # Вывод порта DATA_OUT — накапливаем байты (младший октет слова).
    out_bytes: list[int] = field(default_factory=list)
    # Расписание trap (прерываний по такту): см. io_schedule.load_irq_schedule_json
    irq_schedule: tuple[IrqScheduleEvent, ...] = field(default_factory=tuple)
    _schedule_i: int = field(default=0, repr=False)
    # Последнее значение на линии irq (после события расписания); для отладки/отчёта.
    irq_latches: dict[int, int] = field(default_factory=dict)
    # Линии запроса: расписание ставит pending и байт на линии (не смешивать со stdin).
    irq_pending: list[bool] = field(default_factory=lambda: [False] * NUM_IRQ_LINES)
    irq_line_value: list[int] = field(default_factory=lambda: [0] * NUM_IRQ_LINES)
    irq_enabled: bool = True
    interrupt_depth: int = 0
    # Байт, переданный в обработчик при доставке запроса (читает первый IN на DATA_IN в ISR).
    _irq_delivered_byte: int | None = field(default=None, repr=False)

    def _apply_irq_schedule_for_current_ticks(self) -> None:
        """Зафиксировать события расписания: линия irq, значение на порту, флаг запроса."""
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
            msg = f"Вектор IRQ {irq} вне IM"
            raise CpuFault(msg)
        op_b, opnd = unpack_word(self.im[idx])
        if op_b != int(Opcode.JMP):
            msg = f"Вектор IRQ {irq}: ожидался jmp (word @{idx})"
            raise CpuFault(msg)
        return self._ensure_im_pc(opnd & OPERAND_MASK)

    def _read_port_in(self, port: int) -> int:
        """Значение для IN по номеру порта."""
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
            msg = f"Адрес данных вне диапазона: {addr}"
            raise CpuFault(msg)
        return addr

    def _ensure_im_pc(self, addr: int) -> int:
        if addr < 0 or addr >= IM_SIZE_WORDS:
            msg = f"PC вне диапазона: {addr}"
            raise CpuFault(msg)
        return addr

    def _push(self, value: int) -> None:
        v = value & 0xFFFFFFFF
        if self.sp >= DM_SIZE_WORDS:
            msg = "Переполнение стека (SP)"
            raise CpuFault(msg)
        a = self._ensure_dm_addr(self.sp)
        self.dm[a] = v
        self.sp += 1

    def _pop(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "Недопустимое снятие со стека (пустой стек)"
            raise CpuFault(msg)
        self.sp -= 1
        a = self._ensure_dm_addr(self.sp)
        return self.dm[a] & 0xFFFFFFFF

    def _peek_top(self) -> int:
        if self.sp <= STACK_BASE:
            msg = "Пустой стек при dup/top"
            raise CpuFault(msg)
        a = self._ensure_dm_addr(self.sp - 1)
        return self.dm[a] & 0xFFFFFFFF

    def _add_ticks(self, op: int) -> None:
        self.ticks += _TICKS.get(op, 1)

    def step(self, log: TextIO | None = None) -> None:
        """Одна инструкция (или noop если уже halt)."""
        if self.halted:
            return

        self._apply_irq_schedule_for_current_ticks()

        pc0 = self._ensure_im_pc(self.pc)
        word = self.im[pc0] & 0xFFFFFFFF
        op_byte, operand = unpack_word(word)
        next_pc = pc0 + 1

        if log is not None:
            mode = "ISR" if self.interrupt_depth > 0 else "USR"
            log.write(f"{self.ticks}\t{pc0}\t{word:08X}\t{mode}\n")

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
                self.pc = next_pc
            case x if x == Opcode.LOAD:
                addr = self._pop()
                a = self._ensure_dm_addr(addr)
                self._push(self.dm[a])
                self.pc = next_pc
            case x if x == Opcode.STORE:
                val = self._pop()
                addr = self._pop()
                a = self._ensure_dm_addr(addr)
                self.dm[a] = val & 0xFFFFFFFF
                self.pc = next_pc
            case x if x == Opcode.SWAP:
                top = self._pop()
                below = self._pop()
                self._push(top)
                self._push(below)
                self.pc = next_pc
            case x if x == Opcode.ADD:
                x1 = self._pop()
                y = self._pop()
                self._push((y + x1) & 0xFFFFFFFF)
                self.pc = next_pc
            case x if x == Opcode.SUB:
                x1 = self._pop()
                y = self._pop()
                self._push((y - x1) & 0xFFFFFFFF)
                self.pc = next_pc
            case x if x == Opcode.MUL:
                x1 = self._pop()
                y = self._pop()
                prod = _signed32(y) * _signed32(x1)
                self._push(_unsigned32(prod))
                self.pc = next_pc
            case x if x == Opcode.DIV:
                x1 = self._pop()
                y = self._pop()
                if x1 == 0:
                    raise CpuFault("Целое деление на 0")
                q = math.trunc(_signed32(y) / _signed32(x1))
                self._push(_unsigned32(q))
                self.pc = next_pc
            case x if x == Opcode.MOD:
                x1 = self._pop()
                y = self._pop()
                if x1 == 0:
                    raise CpuFault("Остаток при делении на 0")
                yi, xi = _signed32(y), _signed32(x1)
                r = yi - math.trunc(yi / xi) * xi
                self._push(_unsigned32(r))
                self.pc = next_pc
            case x if x == Opcode.EQ:
                x1 = self._pop()
                y = self._pop()
                self._push(1 if (y & 0xFFFFFFFF) == (x1 & 0xFFFFFFFF) else 0)
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
            case x if x == Opcode.CALL:
                target = operand & OPERAND_MASK
                self._push(next_pc & 0xFFFFFFFF)
                self.pc = self._ensure_im_pc(target)
            case x if x == Opcode.RET:
                addr = self._pop()
                if self.interrupt_depth > 0:
                    self.interrupt_depth -= 1
                self.pc = self._ensure_im_pc(addr & 0xFFFFFFFF)
            case x if x == Opcode.IN:
                port = operand & 0xFFFF
                if (operand >> 16) & 0xFF != 0:
                    pass  # зарезервированные биты — игнор в v0
                val = self._read_port_in(port)
                self._push(_unsigned32(val))
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
                self.pc = next_pc
            case x if x == Opcode.EI:
                self.irq_enabled = True
                self.pc = next_pc
            case x if x == Opcode.CLI:
                self.irq_enabled = False
                self.pc = next_pc
            case x if x == Opcode.HALT:
                self.halted = True
                self.pc = next_pc
            case _:
                msg = f"Неизвестный опкод: 0x{op_byte:02X} в PC={pc0}, слово={word:08X}"
                raise CpuFault(msg)

        self._add_ticks(op)
        if not self.halted:
            self._try_deliver_irq_after_instruction()

    def _try_deliver_irq_after_instruction(self) -> None:
        """После инструкции: один запрос → push адреса следующей команды, PC := обработчик."""
        if self.ticks == 0:
            return
        if not self.irq_enabled:
            return
        if self.interrupt_depth > 0:
            return
        for irq in range(NUM_IRQ_LINES):
            if not self.irq_pending[irq]:
                continue
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
    """Создать IM/DM, начиная с entry PC=0 и data с адреса 0."""
    im = [0] * IM_SIZE_WORDS
    dm = [0] * DM_SIZE_WORDS
    for i, w in enumerate(code_words):
        if i >= IM_SIZE_WORDS:
            msg = "Сегмент кода не помещается в IM"
            raise CpuFault(msg)
        im[i] = w & 0xFFFFFFFF
    for i, w in enumerate(data_words):
        if i >= DM_SIZE_WORDS:
            msg = "Сегмент данных не помещается в DM"
            raise CpuFault(msg)
        dm[i] = w & 0xFFFFFFFF
    return im, dm


def run_program(
    cpu: Cpu,
    *,
    max_ticks: int,
    log: TextIO | None = None,
) -> None:
    """Исполнять до halt, ошибки или лимита суммарных тактов."""
    while not cpu.halted:
        if cpu.ticks >= max_ticks:
            msg = f"Превышен лимит тактов ({max_ticks})"
            raise CpuFault(msg)
        cpu.step(log=log)
