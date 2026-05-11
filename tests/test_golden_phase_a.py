"""golden фазы A — каталоги golden/<case>/"""

from __future__ import annotations

import pytest

from tests.golden_support import read_expected_output, run_case

# prob1: полный перебор 3×3-значных с проверкой палиндрома — тяжёлый кейс
_MAX_TICKS = {"prob1": 100_000_000}


@pytest.mark.parametrize(
    "case",
    ["hello", "cat", "hello_user_name", "pstr_two", "sort", "prob1"],
)
def test_golden_program_output(case: str) -> None:
    cpu = run_case(case, max_ticks=_MAX_TICKS.get(case, 10_000_000))
    assert bytes(cpu.out_bytes) == read_expected_output(case)
