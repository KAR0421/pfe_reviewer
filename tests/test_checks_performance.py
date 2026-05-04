"""Tests for performance checks (SR030 SqlInLoopCheck)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# Importing the module triggers @register_check.
from reviewer.checks import performance  # noqa: F401
from reviewer.engine.runner import run_review
from reviewer_legacy import check_sql_in_loops


FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"


@dataclass
class FakeBizRule:
    name: str
    script: str
    comment: str = ""
    scope: str = ""


def _load(name: str) -> FakeBizRule:
    src = (FIXTURES / name).read_text(encoding="utf-8")
    return FakeBizRule(name=name, script=src)


def _ast_sr030_lines(br: FakeBizRule) -> set[int]:
    report = run_review(br)
    return {f.line for f in report.findings if f.rule_id == "SR030"}


_LEGACY_LINE_RE = re.compile(r"line (\d+) ->")


def _legacy_sr030_lines(br: FakeBizRule) -> set[int]:
    """Extract the offending line numbers from legacy issue strings."""
    issues = check_sql_in_loops(br.script)
    lines: set[int] = set()
    for issue in issues:
        m = _LEGACY_LINE_RE.search(issue)
        if m:
            lines.add(int(m.group(1)))
    return lines


# ── Positive ─────────────────────────────────────────────────────────


def test_sr030_positive_flags_call_line() -> None:
    br = _load("sql_in_foreach.smartrule")
    lines = _ast_sr030_lines(br)
    assert lines == {5}  # the getSqlData call sits on line 5


def test_sr030_positive_message_mentions_outer_loop() -> None:
    br = _load("sql_in_foreach.smartrule")
    report = run_review(br)
    sr030 = [f for f in report.findings if f.rule_id == "SR030"]
    assert len(sr030) == 1
    f = sr030[0]
    assert f.severity == "error"
    assert f.category == "performance"
    # The foreach starts on line 4 in the fixture.
    assert "line 4" in f.message


# ── Negative ────────────────────────────────────────────────────────


def test_sr030_negative_no_findings_outside_loops() -> None:
    br = _load("sql_outside_loop.smartrule")
    assert _ast_sr030_lines(br) == set()


# ── Edge: comments and string literals ──────────────────────────────


def test_sr030_ignores_calls_inside_comments_and_strings() -> None:
    br = _load("sql_in_string_or_comment.smartrule")
    assert _ast_sr030_lines(br) == set()


# ── Diff-test against legacy ────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture_name",
    [
        "sql_in_foreach.smartrule",
        "sql_outside_loop.smartrule",
        # Real fixtures hand-trimmed from sample.pack.xml / sample.pack2.xml.
        # Both contain genuine SQL-in-loop cases; the diff-test asserts
        # the AST and legacy pipelines agree on the offending line numbers.
        "update_document_process.smartrule",
        "compute_template_order.smartrule",
    ],
)
def test_sr030_ast_and_legacy_agree_on_lines(fixture_name: str) -> None:
    """Both pipelines must flag the same set of offending lines.

    Wording may differ; line numbers must not.
    """
    br = _load(fixture_name)
    assert _ast_sr030_lines(br) == _legacy_sr030_lines(br)
