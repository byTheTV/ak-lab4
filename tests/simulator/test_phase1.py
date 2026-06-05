from __future__ import annotations

from ak_lab4.isa import Opcode, pack_word
from ak_lab4.machine import Machine, MachineFault, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE


def test_run_add_then_halt() -> None:
    words = [
        pack_word(Opcode.PUSH_IMM, 5),
        pack_word(Opcode.PUSH_IMM, 3),
        pack_word(Opcode.ADD, 0),
        pack_word(Opcode.HALT, 0),
    ]
    im, dm = init_memory_from_segments(words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=10_000)
    assert machine.halted
    assert machine.sp == STACK_BASE + 1
    assert machine.dm[STACK_BASE] == 8


def test_load_store() -> None:
    data_words = [0] * 0x100 + [42]
    code_words = [
        pack_word(Opcode.PUSH_IMM, 0x100),
        pack_word(Opcode.LOAD, 0),
        pack_word(Opcode.HALT, 0),
    ]
    im, dm = init_memory_from_segments(code_words, data_words)
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(machine, max_ticks=10_000)
    assert machine.halted
    assert machine.sp == STACK_BASE + 1
    assert machine.dm[STACK_BASE] == 42


def test_max_ticks_exceeded() -> None:
    code_words = [pack_word(Opcode.NOP, 0)]
    im, dm = init_memory_from_segments(code_words, [])
    machine = Machine(im=im, dm=dm, pc=0, sp=STACK_BASE)
    try:
        run_program(machine, max_ticks=50)
        raise AssertionError("ожидали MachineFault")
    except MachineFault as e:
        assert "лимит тактов" in str(e)
