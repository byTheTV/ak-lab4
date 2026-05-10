"""Golden hello — см. golden/hello/ и golden/README.md."""

from __future__ import annotations

from tests.golden_support import read_expected_output, run_case


def test_golden_hello_output_matches_fixture() -> None:
    cpu = run_case("hello")
    assert bytes(cpu.out_bytes) == read_expected_output("hello")
