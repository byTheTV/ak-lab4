from __future__ import annotations

from pathlib import Path

from ak_lab4.cpu import Cpu, CpuFault, init_memory_from_segments, run_program
from ak_lab4.isa import Opcode, pack_word
from ak_lab4.loader import write_words_le
from ak_lab4.memory import STACK_BASE


def test_run_add_then_halt(tmp_path: Path) -> None:
    words = [
        pack_word(Opcode.PUSH_IMM, 5),
        pack_word(Opcode.PUSH_IMM, 3),
        pack_word(Opcode.ADD, 0),
        pack_word(Opcode.HALT, 0),
    ]
    code = tmp_path / "code.bin"
    data = tmp_path / "data.bin"
    write_words_le(code, words)
    write_words_le(data, [])

    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=10_000)
    assert cpu.halted
    assert cpu.sp == STACK_BASE + 1
    assert cpu.dm[STACK_BASE] == 8


def test_push_imm_sign_extended(tmp_path: Path) -> None:
    """−1 в 24-бит поле — машинное слово 0xFFFFFF"""
    words = [
        pack_word(Opcode.PUSH_IMM, 0xFFFFFF),  # -1
        pack_word(Opcode.HALT, 0),
    ]
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=1000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 0xFFFFFFFF


def test_load_store(tmp_path: Path) -> None:
    # DM[0x100] = 42 до исполнения — через data.bin?
    data_words = [0] * 0x100 + [42]
    code_words = [
        pack_word(Opcode.PUSH_IMM, 0x100),
        pack_word(Opcode.LOAD, 0),
        pack_word(Opcode.HALT, 0),
    ]
    im, dm = init_memory_from_segments(code_words, data_words)
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=10_000)
    assert cpu.halted
    assert cpu.sp == STACK_BASE + 1
    assert cpu.dm[STACK_BASE] == 42


def test_jmp(tmp_path: Path) -> None:
    # PC 0: jmp to 2; PC 1: halt (skip); PC 2: push 1; halt
    code_words = [
        pack_word(Opcode.JMP, 2),
        pack_word(Opcode.HALT, 0),
        pack_word(Opcode.PUSH_IMM, 1),
        pack_word(Opcode.HALT, 0),
    ]
    im, dm = init_memory_from_segments(code_words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=10_000)
    assert cpu.halted
    assert cpu.dm[STACK_BASE] == 1


def test_max_ticks_exceeded() -> None:
    code_words = [pack_word(Opcode.NOP, 0)]  # бесконечный цикл
    im, dm = init_memory_from_segments(code_words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    try:
        run_program(cpu, max_ticks=50)
        raise AssertionError("ожидали CpuFault")
    except CpuFault as e:
        assert "лимит тактов" in str(e)
