from __future__ import annotations

from ak_lab4.isa import Opcode, Port, pack_word
from ak_lab4.loader import write_words_le
from ak_lab4.simulator.__main__ import main as simulator_main


def test_main_with_input_file_runs(tmp_path) -> None:
    words = [
        pack_word(Opcode.IN, int(Port.DATA_IN)),
        pack_word(Opcode.HALT, 0),
    ]
    code = tmp_path / "code.bin"
    data = tmp_path / "data.bin"
    write_words_le(code, words)
    write_words_le(data, [])
    inp = tmp_path / "stdin.bin"
    inp.write_bytes(b"Z")

    exit_code = simulator_main(
        [str(code), str(data), "--input", str(inp), "--max-ticks", "1000"],
    )
    assert exit_code == 0
