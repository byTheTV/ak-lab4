from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_support import (
    GOLDEN_ROOT,
    example_lisp_path,
    format_output,
    golden_yml_paths,
    load_example_source,
    load_golden_yml,
    run_from_yml,
)


@pytest.mark.parametrize("path", golden_yml_paths())
def test_golden_yml(path: Path) -> None:
    expected = load_golden_yml(path)
    actual = run_from_yml(path)
    assert format_output(actual.output) == expected["output"]
    assert actual.log_excerpt == expected["log_excerpt"]
    assert actual.code_listing == expected["code_listing"]
    assert actual.data_listing == expected["data_listing"]


def test_golden_prob1_superscalar_output() -> None:
    path = GOLDEN_ROOT / "prob1.yml"
    expected = load_golden_yml(path)
    actual = run_from_yml(path, superscalar=True)
    assert format_output(actual.output) == expected["output"]


def test_prob1_example_matches_golden_source() -> None:
    golden = load_golden_yml(GOLDEN_ROOT / "prob1.yml")
    assert example_lisp_path("prob1").is_file()
    assert golden["source"] == load_example_source("prob1")


def test_golden_cases_required() -> None:
    names = {p.stem for p in golden_yml_paths()}
    required = {
        "hello",
        "cat",
        "hello_user_name",
        "sort",
        "double_math",
        "prob1",
    }
    assert required <= names
