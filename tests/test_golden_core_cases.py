from __future__ import annotations

import pytest

from ak_lab4.loader import load_words_le
from tests.golden_support import (
    CODE_BIN,
    CODE_LISTING,
    DATA_BIN,
    DATA_LISTING,
    TRACE_LOG,
    all_golden_cases,
    capture_trace,
    compile_case,
    format_listing,
    golden_dir,
    read_golden_output,
    read_golden_text,
    run_case,
)

_ALL_GOLDEN_CASES = all_golden_cases()


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_output_txt(case: str) -> None:
    machine = run_case(case)
    assert bytes(machine.out_bytes) == read_golden_output(case)


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_code_bin(case: str) -> None:
    compiled = compile_case(case)
    golden = load_words_le(golden_dir(case) / CODE_BIN)
    assert compiled.code == golden


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_data_bin(case: str) -> None:
    compiled = compile_case(case)
    golden = load_words_le(golden_dir(case) / DATA_BIN)
    assert compiled.data == golden


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_code_listing(case: str) -> None:
    compiled = compile_case(case)
    assert format_listing(compiled.code) == read_golden_text(case, CODE_LISTING)


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_data_listing(case: str) -> None:
    compiled = compile_case(case)
    assert format_listing(compiled.data) == read_golden_text(case, DATA_LISTING)


@pytest.mark.parametrize("case", _ALL_GOLDEN_CASES)
def test_golden_trace_log(case: str) -> None:
    assert capture_trace(case) == read_golden_text(case, TRACE_LOG)


def test_golden_prob1_superscalar_output() -> None:
    case = "prob1"
    machine = run_case(case, superscalar=True)
    assert bytes(machine.out_bytes) == read_golden_output(case)
