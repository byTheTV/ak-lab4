from __future__ import annotations

from ak_lab4.cpu import Cpu, init_memory_from_segments, run_program
from ak_lab4.memory import STACK_BASE
from ak_lab4.translator import parse
from ak_lab4.translator.codegen import compile_program


def _run(src: str) -> Cpu:
    words = compile_program(parse(src)).code
    im, dm = init_memory_from_segments(words, [])
    cpu = Cpu(im=im, dm=dm, pc=0, sp=STACK_BASE)
    run_program(cpu, max_ticks=50_000)
    assert cpu.halted
    return cpu


def test_load_store_roundtrip() -> None:
    cpu = _run(
        "(progn (store 10 42) (out (load 10)))",
    )
    assert cpu.out_bytes == [42]


def test_store_in_progn_with_read_el_shape() -> None:
    """регрессия: store не должен снимать ret с стека внутри progn"""
    cpu = _run(
        "(progn (store 20 7) (out (load 20)))",
    )
    assert cpu.out_bytes == [7]
