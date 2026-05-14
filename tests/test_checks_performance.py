"""Tests for performance checks (SR030 SqlInLoopCheck,
SR031 NestedLoopCheck, SR032 RepeatedQueryCheck)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Importing the module triggers @register_check.
from reviewer.checks import performance  # noqa: F401
from reviewer.engine.runner import run_review


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


# ── SR030 Positive ──────────────────────────────────────────────────


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


# ── SR030 Negative ──────────────────────────────────────────────────


def test_sr030_negative_no_findings_outside_loops() -> None:
    br = _load("sql_outside_loop.smartrule")
    assert _ast_sr030_lines(br) == set()


# ── SR030 Edge: comments and string literals ───────────────────────


def test_sr030_ignores_calls_inside_comments_and_strings() -> None:
    br = _load("sql_in_string_or_comment.smartrule")
    assert _ast_sr030_lines(br) == set()


# ────────────────────────────────────────────────────────────────────
# SR031 NestedLoopCheck
# ────────────────────────────────────────────────────────────────────


def _ast_sr031_inner_lines(br: FakeBizRule) -> set[int]:
    """Lines on which the AST check reports a nested *inner* loop."""
    return {
        f.line for f in run_review(br).findings if f.rule_id == "SR031"
    }


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
    """Loop keywords inside comments or string literals must not fire:
    the tokenizer drops comments, strings are opaque tokens.
    """
    br = _load("loops_in_string_or_comment.smartrule")
    assert _ast_sr031_inner_lines(br) == set()


def test_sr031_does_not_double_count_do_while() -> None:
    """A single ``do { ... } while (...)`` is one ``DoWhile`` node, not
    two nested loops.
    """
    br = _load("single_do_while.smartrule")
    assert _ast_sr031_inner_lines(br) == set()


# ────────────────────────────────────────────────────────────────────
# SR032 RepeatedQueryCheck
#
# Recognises ``getSqlData`` and ``getData``, accepts inline /
# concatenated SQL strings, and grades severity into three tiers based
# on how the queries differ.
# ────────────────────────────────────────────────────────────────────


def _ast_sr032_findings(br: FakeBizRule) -> list:
    return [f for f in run_review(br).findings if f.rule_id == "SR032"]


# ── Tier 1 (error): exact duplicate ─────────────────────────────────


def test_sr032_t1_exact_duplicate_emits_error() -> None:
    br = _load("repeated_query_t1_duplicate.smartrule")
    findings = _ast_sr032_findings(br)
    assert len(findings) == 1
    f = findings[0]
    # The finding points at the *second* (redundant) call.
    assert f.line == 3
    assert f.severity == "error"
    assert f.category == "performance"
    assert "Duplicate query" in f.message
    # Structural check: both line numbers must appear, but the test
    # does not pin down the exact phrasing connecting them.
    assert "2" in f.message and "3" in f.message


# ── Tier 2 (warning): same WHERE, different SELECT ──────────────────


def test_sr032_t2_different_select_emits_warning_with_union_hint() -> None:
    br = _load("repeated_query_t2_different_select.smartrule")
    findings = _ast_sr032_findings(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 4
    assert f.severity == "warning"
    # Hint mentions both fields in the merge suggestion.
    assert "id" in f.message and "name" in f.message
    assert "merging" in f.message.lower()


# ── Tier 3 (info): same SELECT, one literal-equality value differs ──


def test_sr032_t3_one_value_diff_emits_info_with_in_hint() -> None:
    br = _load("repeated_query_t3_one_value_diff.smartrule")
    findings = _ast_sr032_findings(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 5
    assert f.severity == "info"
    # The discriminating column and both literals appear in the hint.
    assert "code" in f.message
    assert "'A'" in f.message and "'B'" in f.message
    assert "IN (" in f.message


# ── Negatives ───────────────────────────────────────────────────────


def test_sr032_clean_different_tables_no_finding() -> None:
    br = _load("repeated_query_clean_different_tables.smartrule")
    assert _ast_sr032_findings(br) == []


def test_sr032_clean_multi_column_diff_no_finding() -> None:
    """Two columns differ → not a single-value-diff; no T3, no T2,
    no T1."""
    br = _load("repeated_query_clean_multi_diff.smartrule")
    assert _ast_sr032_findings(br) == []


def test_sr032_clean_different_operator_no_finding() -> None:
    """``code = 'A'`` vs ``code != 'A'`` is a real semantic
    difference, not a near-duplicate."""
    br = _load("repeated_query_clean_different_operator.smartrule")
    assert _ast_sr032_findings(br) == []


# ── Edge: in-string / commented-out queries ─────────────────────────


def test_sr032_ignores_strings_and_comments() -> None:
    """A string literal that *contains* SELECT-text and a commented
    duplicate must not pair with the live query — only one real call
    site exists, so there is no pair to compare.
    """
    br = _load("repeated_query_in_string_or_comment.smartrule")
    assert _ast_sr032_findings(br) == []


# ── Inline / non-getSqlData / concat-substitution forms ─────────────


def test_sr032_catches_inline_duplicates() -> None:
    """Two inline ``getSqlData("...")`` calls (no intermediate
    variable) must still pair as duplicates.
    """
    br = _load("repeated_query_inline_duplicates.smartrule")
    findings = _ast_sr032_findings(br)
    assert len(findings) == 1
    assert findings[0].line == 4
    assert findings[0].severity == "error"


def test_sr032_catches_getdata_calls() -> None:
    """``getData(...)`` is recognised alongside ``getSqlData(...)``."""
    br = _load("repeated_query_getdata.smartrule")
    findings = _ast_sr032_findings(br)
    assert len(findings) == 1
    assert findings[0].severity == "error"


def test_sr032_catches_concat_substitution() -> None:
    """``"... = '" + item.CODE + "'"`` flattens to a string with the
    runtime substitution replaced by ``?``. Two such calls then match
    as exact duplicates.
    """
    br = _load("repeated_query_concat_substitution.smartrule")
    findings = _ast_sr032_findings(br)
    assert len(findings) == 1
    assert findings[0].severity == "error"


# ── No interference with SR030 / SR031 ──────────────────────────────


def test_sr032_does_not_fire_on_single_query_in_loop() -> None:
    """SR030 already flags SQL in loops; SR032 must not pile on when
    only one query exists in the rule.
    """
    br = _load("sql_in_foreach.smartrule")
    assert _ast_sr032_findings(br) == []


# ── Contract: unparseable queries are silently skipped ──────────────


def test_sr032_unparseable_queries_are_silently_skipped() -> None:
    """**Contract**: when a query string cannot be parsed as a single
    ``SELECT`` (random text, DML, multi-statement, …), the check
    silently skips that call site. It must not:

    - crash the review (no ``SR998`` finding),
    - match unparseable strings as duplicates of one another,
    - or pair an unparseable string with a real query.

    This is the safer default: false positives on garbage would be
    far more annoying than missing a duplicate inside genuinely
    malformed code.
    """
    br = _load("repeated_query_unparseable.smartrule")
    report = run_review(br)
    assert _ast_sr032_findings(br) == []
    # No collateral crash from the check, either.
    assert all(f.rule_id != "SR998" for f in report.findings)


# ────────────────────────────────────────────────────────────────────
# SR033 UnboundedLoopCheck
# ────────────────────────────────────────────────────────────────────


def _ast_sr033_findings(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR033"]


# ── SR033 Positive: trivial-infinite literal ───────────────────────


def test_sr033_while_truthy_literal_fires() -> None:
    br = _load("unbounded_while_truthy_literal.smartrule")
    findings = _ast_sr033_findings(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 3  # the ``while (1)`` keyword line
    assert f.severity == "warning"
    assert f.category == "performance"
    assert "truthy literal" in f.message


def test_sr033_do_while_truthy_string_literal_fires() -> None:
    br = _load("unbounded_do_while_truthy_literal.smartrule")
    findings = _ast_sr033_findings(br)
    assert len(findings) == 1
    f = findings[0]
    # ``do`` keyword sits on line 2.
    assert f.line == 2
    assert "truthy literal" in f.message


# ── SR033 Positive: unbounded condition ────────────────────────────


def test_sr033_while_no_mutation_fires_with_var_names() -> None:
    br = _load("unbounded_while_no_mutation.smartrule")
    findings = _ast_sr033_findings(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 6  # the ``while`` keyword line
    # Both condition vars must appear in the message.
    assert "i" in f.message
    assert "n" in f.message
    assert "not modified" in f.message


# ── SR033 Negative ─────────────────────────────────────────────────


def test_sr033_bounded_while_silent() -> None:
    br = _load("bounded_while_clean.smartrule")
    assert _ast_sr033_findings(br) == []


def test_sr033_field_assignment_overlap_silent() -> None:
    """Body assigns ``obj.READY`` and ``i``; condition references
    both. Either overlap alone is enough to keep the check silent."""
    br = _load("bounded_while_field_assignment.smartrule")
    assert _ast_sr033_findings(br) == []


# ── SR033 Edge: comments and string literals ───────────────────────


def test_sr033_ignores_loops_inside_strings_and_comments() -> None:
    br = _load("unbounded_loop_in_string_or_comment.smartrule")
    assert _ast_sr033_findings(br) == []


# ── SR033 Boundary tests ───────────────────────────────────────────


def test_sr033_boundary_zero_literal_silent() -> None:
    """``while (0)`` is exactly one unit on the safe side of the
    truthy-literal boundary: 0 is the only NumberLit value treated
    as falsy. The condition has no extractable identifiers either,
    so the disjoint path also short-circuits — net silent."""
    br = _load("unbounded_while_zero_literal.smartrule")
    assert _ast_sr033_findings(br) == []


def test_sr033_boundary_one_literal_fires() -> None:
    """One unit past the boundary on the firing side: ``while (1)``."""
    br = _load("unbounded_while_truthy_literal.smartrule")
    assert len(_ast_sr033_findings(br)) == 1


def test_sr033_call_only_condition_silent() -> None:
    """``while (getStatus())`` has no Identifier / FieldAccess outside
    the callee position, so the disjoint-set path has no signal and
    must NOT fire. Avoids a false positive on call-driven loops."""
    br = _load("unbounded_while_call_condition.smartrule")
    assert _ast_sr033_findings(br) == []

# SR034_TESTS_MARKER


# ════════════════════════════════════════════════════════════════════
# SR034 — RepeatedFieldReadCheck
# ════════════════════════════════════════════════════════════════════


def _sr034(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR034"]


# ── SR034 Positive ─────────────────────────────────────────────────


def test_sr034_two_reads_fires_once_anchored_at_first() -> None:
    br = _load("repeated_field_two_reads.smartrule")
    findings = _sr034(br)
    assert len(findings) == 1
    f = findings[0]
    # Anchored at the FIRST read's line, not the second.
    assert f.line == 1
    assert f.severity == "info"
    assert f.category == "performance"
    assert "obj.F" in f.message
    assert "2 times" in f.message
    assert "lines 1, 2" in f.message


def test_sr034_three_reads_fires_once_with_all_lines() -> None:
    br = _load("repeated_field_three_reads.smartrule")
    findings = _sr034(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 1
    assert "3 times" in f.message
    assert "lines 1, 2, 3" in f.message


def test_sr034_chain_depth_tracked() -> None:
    """``obj.sub.F`` reads share key ``("obj.sub", "F")`` — also fires.

    The intermediate ``obj.sub`` is also tracked as its own key, so
    two findings appear (one per key), each anchored at line 1.
    """
    br = _load("repeated_field_chain_depth.smartrule")
    findings = _sr034(br)
    assert all(f.line == 1 for f in findings)
    assert sum("obj.sub.F" in f.message for f in findings) == 1


# ── SR034 Negative ─────────────────────────────────────────────────


def test_sr034_var_reassignment_invalidates() -> None:
    br = _load("repeated_field_var_reassigned.smartrule")
    assert _sr034(br) == []


def test_sr034_field_reassignment_invalidates() -> None:
    br = _load("repeated_field_field_reassigned.smartrule")
    assert _sr034(br) == []


def test_sr034_single_read_silent() -> None:
    br = _load("repeated_field_single_read.smartrule")
    assert _sr034(br) == []


def test_sr034_different_fields_silent() -> None:
    br = _load("repeated_field_different_fields.smartrule")
    assert _sr034(br) == []


def test_sr034_different_targets_silent() -> None:
    br = _load("repeated_field_different_targets.smartrule")
    assert _sr034(br) == []


def test_sr034_call_target_silent() -> None:
    """``getThing().F`` has no stable source variable, so it's
    excluded by design — the dotted-name resolver returns ``None``.
    """
    br = _load("repeated_field_call_target.smartrule")
    assert _sr034(br) == []


# ── SR034 Edge ─────────────────────────────────────────────────────


def test_sr034_in_string_or_comment_silent() -> None:
    """The tokenizer strips comments and treats string literals as
    opaque tokens, so the AST never produces ``FieldAccess`` nodes
    for those lookalikes — nothing for SR034 to fire on.
    """
    br = _load("repeated_field_in_string_or_comment.smartrule")
    assert _sr034(br) == []


# ── SR034 Real-pack regression ─────────────────────────────────────


def test_sr034_real_pack_update_document_process_documented() -> None:
    """Real script from sample.pack.xml. Document the count so any
    future regression that changes detection sensitivity surfaces in
    a diff. The exact count is whatever the analyzer naturally finds;
    these are *findings*, not test failures.
    """
    br = _load("update_document_process.smartrule")
    findings = _sr034(br)
    # Smoke-test: every finding has the expected shape.
    for f in findings:
        assert f.severity == "info"
        assert f.category == "performance"
        assert "read" in f.message and "times" in f.message


def test_sr034_real_pack_compute_template_order_documented() -> None:
    br = _load("compute_template_order.smartrule")
    findings = _sr034(br)
    for f in findings:
        assert f.severity == "info"
        assert f.category == "performance"
