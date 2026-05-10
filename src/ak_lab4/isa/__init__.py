"""ISA v0: опкоды и порты без логики исполнения"""

from __future__ import annotations

from enum import IntEnum

# Битовая раскладка 32-бит слова: [31:24] op, [23:0] operand
OPCODE_SHIFT: int = 24
OPERAND_MASK: int = 0xFFFFFF

# линии IRQ в --schedule и вектора IM[1..N]
NUM_IRQ_LINES: int = 8


class Opcode(IntEnum):
    """старший байт машинного слова"""

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
    SLT = 0x16  # signed: pop b, pop a; push 1 если a < b, иначе 0
    JMP = 0x20
    JZ = 0x21
    CALL = 0x22
    RET = 0x23
    IN = 0x30
    OUT = 0x31
    HALT = 0x32
    EI = 0x33  # разрешить маскируемые прерывания
    CLI = 0x34  # запретить маскируемые прерывания


class Port(IntEnum):
    """номер порта в младших 16 битах операнда IN/OUT"""

    DATA_IN = 0
    DATA_OUT = 1
    IRQ_STATUS = 2
    IRQ_EOI = 3


def pack_word(op: Opcode, operand: int = 0) -> int:
    """одно слово команды; операнд режется до 24 бит"""
    return ((int(op) & 0xFF) << OPCODE_SHIFT) | (operand & OPERAND_MASK)


def unpack_word(word: int) -> tuple[int, int]:
    """(op, operand) из 32-бит слова"""
    w = word & 0xFFFFFFFF
    return (w >> OPCODE_SHIFT) & 0xFF, w & OPERAND_MASK


def sign_extend_operand_i(operand: int) -> int:
    """24-бит знаковый операнд → int32"""
    o = operand & OPERAND_MASK
    if o & 0x800000:
        return o - 0x1000000
    return o
