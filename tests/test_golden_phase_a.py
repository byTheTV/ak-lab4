"""Golden-сценарии фазы A — см. ``golden/<case>/`` и ``golden/README.md``."""

from __future__ import annotations

import pytest

from tests.golden_support import read_expected_output, run_case


@pytest.mark.parametrize("case", ["hello", "cat"])
def test_golden_program_output(case: str) -> None:
    cpu = run_case(case)
    assert bytes(cpu.out_bytes) == read_expected_output(case)
