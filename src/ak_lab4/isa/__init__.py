"""Константы ISA v0: только опкоды и порты, без логики исполнения."""

from __future__ import annotations

from enum import IntEnum

# Битовая раскладка 32-бит слова: [31:24] op, [23:0] operand
OPCODE_SHIFT: int = 24
OPERAND_MASK: int = 0xFFFFFF


class Opcode(IntEnum):
    """Коды операций (старший байт слова)."""

    NOP = 0x00
    PUSH_IMM = 0x01
    DUP = 0x02
    DROP = 0x03
    LOAD = 0x04
    STORE = 0x05
    SWAP = 0x06
    ADD = 0x10
    SUB = 0x11
    MUL = 0x12
    DIV = 0x13
    MOD = 0x14
    EQ = 0x15
    JMP = 0x20
    JZ = 0x21
    CALL = 0x22
    RET = 0x23
    IN = 0x30
    OUT = 0x31
    HALT = 0x32


class Port(IntEnum):
    """Порт-mapped I/O (младшие 16 бит operand для IN/OUT)."""

    DATA_IN = 0
    DATA_OUT = 1
    IRQ_STATUS = 2
    IRQ_EOI = 3


def pack_word(op: Opcode, operand: int = 0) -> int:
    """Упаковать одно слово инструкции (operand обрезается до 24 бит)."""
    return ((int(op) & 0xFF) << OPCODE_SHIFT) | (operand & OPERAND_MASK)


def unpack_word(word: int) -> tuple[int, int]:
    """Вернуть (op, operand) из 32-бит слова."""
    w = word & 0xFFFFFFFF
    return (w >> OPCODE_SHIFT) & 0xFF, w & OPERAND_MASK


def sign_extend_operand_i(operand: int) -> int:
    """Формат I: 24-битное знаковое поле → 32-бит int."""
    o = operand & OPERAND_MASK
    if o & 0x800000:
        return o - 0x1000000
    return o
