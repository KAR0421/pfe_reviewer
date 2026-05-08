"""Tests for performance checks (SR030 SqlInLoopCheck)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# Importing the module triggers @register_check.
from reviewer.checks import performance  # noqa: F401
from reviewer.engine.runner import run_review
from reviewer_legacy import check_sql_in_loops, check_nested_loops


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


# ────────────────────────────────────────────────────────────────────
# SR031 NestedLoopCheck
# ────────────────────────────────────────────────────────────────────


def _ast_sr031_inner_lines(br: FakeBizRule) -> set[int]:
    """Lines on which the AST check reports a nested *inner* loop."""
    return {
        f.line for f in run_review(br).findings if f.rule_id == "SR031"
    }


# Legacy messages look like:
#   "Nested loop detected: outer loop at line 27, inner loop at line 28"
_LEGACY_INNER_LINE_RE = re.compile(r"inner loop at line (\d+)")


def _legacy_sr031_inner_lines(br: FakeBizRule) -> set[int]:
    out: set[int] = set()
    for issue in check_nested_loops(br.script):
        m = _LEGACY_INNER_LINE_RE.search(issue)
        if m:
            out.add(int(m.group(1)))
    return out


# ── Positive ─────────────────────────────────────────────────────────


def test_sr031_positive_flags_inner_loop_line() -> None:
    br = _load("nested_loops_simple.smartrule")
    # Outer foreach on line 2, inner foreach on line 4.
    assert _ast_sr031_inner_lines(br) == {4}


def test_sr031_positive_message_names_outer_and_inner() -> None:
    br = _load("nested_loops_simple.smartrule")
    sr031 = [f for f in run_review(br).findings if f.rule_id == "SR031"]
    assert len(sr031) == 1
    f = sr031[0]
    # No expensive call inside, neither bound is a literal counter →
    # default "warning" severity.
    assert f.severity == "warning"
    assert f.category == "performance"
    assert "line 2" in f.message  # outer
    assert "line 4" in f.message  # inner


# ── Severity grading ────────────────────────────────────────────────


def test_sr031_severity_error_when_inner_body_has_sql_call() -> None:
    """Nested loop with ``getSqlData`` inside the inner body → error."""
    br = _load("nested_loops_with_sql.smartrule")
    sr031 = [f for f in run_review(br).findings if f.rule_id == "SR031"]
    assert len(sr031) == 1
    assert sr031[0].severity == "error"


def test_sr031_severity_error_when_inner_body_has_getobject_call() -> None:
    """Nested loop with ``getObjects`` inside the inner body → error.

    Exercises the ``getobject`` prefix rule in ``EXPENSIVE_FUNCTIONS``.
    """
    br = _load("nested_loops_with_getobject.smartrule")
    sr031 = [f for f in run_review(br).findings if f.rule_id == "SR031"]
    assert len(sr031) == 1
    assert sr031[0].severity == "error"


def test_sr031_severity_info_when_both_loops_bounded_by_literals() -> None:
    """Two nested ``for X := <num> to <num>`` loops → info."""
    br = _load("nested_loops_bounded.smartrule")
    sr031 = [f for f in run_review(br).findings if f.rule_id == "SR031"]
    assert len(sr031) == 1
    assert sr031[0].severity == "info"


# ── Negative ────────────────────────────────────────────────────────


def test_sr031_negative_sibling_loops_not_nested() -> None:
    br = _load("sibling_loops.smartrule")
    assert _ast_sr031_inner_lines(br) == set()


# ── Edge: comments / strings / single do-while ──────────────────────


def test_sr031_ignores_loop_keywords_in_comments_and_strings() -> None:
    """Legacy regex matched ``for``/``while``/``do`` substrings inside
    comments and string literals, easily reporting "nesting" where
    there are no real loops at all. The AST pipeline tokenizes strings
    as opaque tokens and discards comments, so this whole class of
    false positive is gone.
    """
    br = _load("loops_in_string_or_comment.smartrule")
    assert _ast_sr031_inner_lines(br) == set()


def test_sr031_does_not_double_count_do_while() -> None:
    """Legacy false positive: a single ``do { ... } while (...)`` was
    reported as a nested loop because the regex pushed two stack
    frames — one on the ``do`` line and one on the closing ``while``
    line. The AST sees one ``DoWhile`` node.
    """
    br = _load("single_do_while.smartrule")
    assert _ast_sr031_inner_lines(br) == set()


# ── Diff-test: AST findings ⊆ legacy findings ───────────────────────


def test_sr031_clean_fixture_strict_agreement() -> None:
    """On a script with sibling (non-nested) loops, both pipelines
    must agree on the empty set.
    """
    br = _load("sibling_loops.smartrule")
    assert (
        _ast_sr031_inner_lines(br)
        == _legacy_sr031_inner_lines(br)
        == set()
    )


@pytest.mark.parametrize(
    "fixture_name",
    [
        # Real positive — both pipelines agree on the inner-loop line(s).
        "nested_loops_simple.smartrule",
        # Severity-graded positives — legacy emits the same line(s)
        # without grading; AST line set must stay a subset.
        "nested_loops_with_sql.smartrule",
        "nested_loops_with_getobject.smartrule",
        "nested_loops_bounded.smartrule",
        # Comments/strings: legacy false positives, AST silent.
        "loops_in_string_or_comment.smartrule",
        # do-while double-count legacy FP, AST silent.
        "single_do_while.smartrule",
        # Real fixtures with several real nested-loop cases plus
        # legacy brace-desync artifacts.
        "update_document_process.smartrule",
        "compute_template_order.smartrule",
    ],
)
def test_sr031_ast_lines_are_subset_of_legacy(fixture_name: str) -> None:
    """The AST check must not regress recall: every line it flags must
    also be flagged by legacy. Legacy may flag *more* lines — those
    are legacy false positives the AST pipeline correctly suppresses
    (comments, strings, do-while double-count, brace de-sync from
    ``}`` closing non-loop blocks).
    """
    br = _load(fixture_name)
    ast_lines = _ast_sr031_inner_lines(br)
    legacy_lines = _legacy_sr031_inner_lines(br)
    assert ast_lines <= legacy_lines, (
        f"AST flagged inner-loop lines {ast_lines - legacy_lines} that "
        f"legacy did not — recall regression."
    )
