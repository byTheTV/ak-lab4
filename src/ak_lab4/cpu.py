"""Модель CPU: PC/SP, такты, исполнение по таблице opcodes v0."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TextIO

from ak_lab4.isa import OPERAND_MASK, Opcode, Port, sign_extend_operand_i, unpack_word
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
    # Заглушка ввода: всегда 0; вывод порта 1 — накапливаем байты (младший октет)
    out_bytes: list[int] = field(default_factory=list)

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

        pc0 = self._ensure_im_pc(self.pc)
        word = self.im[pc0] & 0xFFFFFFFF
        op_byte, operand = unpack_word(word)
        next_pc = pc0 + 1

        if log is not None:
            log.write(f"{self.ticks}\t{pc0}\t{word:08X}\n")

        op = op_byte
        self._add_ticks(op)

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
                self.pc = self._ensure_im_pc(addr & 0xFFFFFFFF)
            case x if x == Opcode.IN:
                port = operand & 0xFFFF
                if (operand >> 16) & 0xFF != 0:
                    pass  # зарезервированные биты — игнор в v0
                # Заглушка: всегда 0 (trap/ввод — часть 2)
                _ = port
                self._push(0)
                self.pc = next_pc
            case x if x == Opcode.OUT:
                val = self._pop()
                port = operand & 0xFFFF
                if port == int(Port.DATA_OUT):
                    self.out_bytes.append(val & 0xFF)
                self.pc = next_pc
            case x if x == Opcode.HALT:
                self.halted = True
                self.pc = next_pc
            case _:
                msg = f"Неизвестный опкод: 0x{op_byte:02X} в PC={pc0}, слово={word:08X}"
                raise CpuFault(msg)


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
