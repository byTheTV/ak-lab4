from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_support import read_expected_output, run_case

_MAX_TICKS = {"prob1": 65_000_000}
_GOLDEN_ROOT = Path(__file__).resolve().parent.parent / "golden"
_ALL_GOLDEN_CASES = tuple(
    sorted(
        case_dir.name
        for case_dir in _GOLDEN_ROOT.iterdir()
        if case_dir.is_dir()
        and (case_dir / "source.tv").is_file()
        and (case_dir / "expected_output.txt").is_file()
    ),
)


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_output_all_cases(case: str) -> None:
    cpu = run_case(case, max_ticks=_MAX_TICKS.get(case, 10_000_000))
    assert bytes(cpu.out_bytes) == read_expected_output(case)


def test_golden_output_prob1_superscalar() -> None:
    case = "prob1"
    cpu = run_case(
        case,
        max_ticks=_MAX_TICKS.get(case, 10_000_000),
        superscalar=True,
    )
    assert bytes(cpu.out_bytes) == read_expected_output(case)
