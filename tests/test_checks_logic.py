"""Tests for logic checks (SR020 StaticConditionCheck,
SR021 DeadCodeCheck)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

# Importing the package triggers @register_check for every check.
from reviewer import checks as _checks  # noqa: F401
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


def _ast_sr021_terminator_lines(br: FakeBizRule) -> set[int]:
    """Return the set of terminator lines flagged by SR021.

    Convention: ``Finding.line`` points at the terminator (e.g. the
    ``return`` line), not at the unreachable successor.
    """
    return {
        f.line for f in run_review(br).findings if f.rule_id == "SR021"
    }


# ── Positive ─────────────────────────────────────────────────────────


def test_sr021_positive_flags_terminator_line() -> None:
    br = _load("dead_code_after_return.smartrule")
    # The return is on line 6; the dead msginfo on line 7. Finding.line
    # points at the terminator (6).
    assert _ast_sr021_terminator_lines(br) == {6}


def test_sr021_positive_message_names_terminator_and_successor() -> None:
    br = _load("dead_code_after_return.smartrule")
    report = run_review(br)
    sr021 = [f for f in report.findings if f.rule_id == "SR021"]
    assert len(sr021) == 1
    f = sr021[0]
    assert f.severity == "warning"
    assert f.category == "logic"
    assert "return" in f.message
    assert "line 7" in f.message  # successor line is named in message


# ── Negative ────────────────────────────────────────────────────────


def test_sr021_negative_no_findings_when_terminator_is_last() -> None:
    br = _load("dead_code_clean.smartrule")
    assert _ast_sr021_terminator_lines(br) == set()


# ── Edge: comments and string literals ──────────────────────────────


def test_sr021_ignores_terminators_inside_comments_and_strings() -> None:
    """Terminators inside comments or string literals must not fire:
    the tokenizer drops comments, and strings are opaque tokens.
    """
    br = _load("dead_code_in_string_or_comment.smartrule")
    assert _ast_sr021_terminator_lines(br) == set()


def test_sr021_does_not_flag_else_branch_after_return_in_if() -> None:
    """``if (x) { return; } else { ... }`` must not flag the else
    branch: the return lives inside the then-branch's own Block, so
    the else-branch — and any code after the whole if — is reachable.
    """
    br = _load("dead_code_in_if_else_branches.smartrule")
    assert _ast_sr021_terminator_lines(br) == set()


# ════════════════════════════════════════════════════════════════════
# SR020 StaticConditionCheck
# ════════════════════════════════════════════════════════════════════


def _ast_sr020_lines(br: FakeBizRule) -> set[int]:
    return {f.line for f in run_review(br).findings if f.rule_id == "SR020"}


# ── Positive ────────────────────────────────────────────────────────


def test_sr020_positive_literal_eq() -> None:
    br = _load("static_cond_literal_eq.smartrule")
    # `if (1 = 1)` is on line 3.
    assert _ast_sr020_lines(br) == {3}


def test_sr020_positive_severity_is_error() -> None:
    """User policy: any literal-vs-literal condition is wrong regardless
    of context — reviewer must fire loudly, not as a warning."""
    br = _load("static_cond_literal_eq.smartrule")
    sr020 = [f for f in run_review(br).findings if f.rule_id == "SR020"]
    assert len(sr020) == 1
    assert sr020[0].severity == "error"
    assert sr020[0].category == "logic"


# ── Negative ────────────────────────────────────────────────────────


def test_sr020_negative_dynamic_and_bare_truthy() -> None:
    """`if (x = 1)` and `if (x)` must NOT be flagged. The second form is
    the idiomatic null/truthy check in this language and is widespread
    in real BizRules — flagging it would drown the user in noise.
    """
    br = _load("static_cond_dynamic.smartrule")
    assert _ast_sr020_lines(br) == set()


# ── Edge: comments and string literals ─────────────────────────────


def test_sr020_ignores_conditions_inside_comments_and_strings() -> None:
    """Conditions inside comments and string literals must not fire:
    the tokenizer drops comments, strings are opaque tokens.
    """
    br = _load("static_cond_in_string_or_comment.smartrule")
    assert _ast_sr020_lines(br) == set()


# ── Structural patterns ───────────────────────────────────


def test_sr020_self_compare_field_access() -> None:
    """``obj.F = obj.F`` — two ``FieldAccess`` trees compared for
    structural equality fire as a tautology.
    """
    br = _load("static_cond_self_field.smartrule")
    assert _ast_sr020_lines(br) == {2}


def test_sr020_self_compare_call() -> None:
    """``f(x) = f(x)`` — same callee, same args structurally; fires.
    Generalises to ``f(a, b) = f(a, b)`` etc.
    """
    br = _load("static_cond_self_call.smartrule")
    assert _ast_sr020_lines(br) == {2}


def test_sr020_trivial_subcondition() -> None:
    """``1 = 1 and x`` — the dead conjunct is caught by recursing
    through ``and``/``or``. Severity: error — leftover debug code is
    loud, not redeemed by the live conjunct.
    """
    br = _load("static_cond_trivial_sub.smartrule")
    findings = [
        f for f in run_review(br).findings if f.rule_id == "SR020"
    ]
    assert {f.line for f in findings} == {2}
    assert all(f.severity == "error" for f in findings)


def test_sr020_parens_are_transparent() -> None:
    """``(x) = x`` — the parser drops redundant parens, so structural
    equality still fires.
    """
    br = _load("static_cond_parens.smartrule")
    assert _ast_sr020_lines(br) == {2}


# ════════════════════════════════════════════════════════════════════
# SR041 — DivByZeroCheck
# ════════════════════════════════════════════════════════════════════


def _sr041(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR041"]


# ── Positive — KNOWN_ZERO (error) ─────────────────────────────────


def test_sr041_literal_zero_fires_error() -> None:
    br = _load("div_zero_literal.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "error"
    assert f.category == "logic"
    assert f.line == 1
    assert "Division by zero" in f.message
    assert "y / 0" in f.message


def test_sr041_then_of_eq_zero_fires_error() -> None:
    br = _load("div_zero_then_eq_zero.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].line == 2  # the division line
    assert "total / y" in findings[0].message


def test_sr041_else_of_ne_zero_fires_error() -> None:
    br = _load("div_zero_else_ne_zero.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].line == 4


def test_sr041_then_of_not_y_fires_error() -> None:
    br = _load("div_zero_then_not_y.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].line == 2


# ── Positive — UNKNOWN (warning) ──────────────────────────────────


def test_sr041_unguarded_simple_fires_warning() -> None:
    br = _load("div_unguarded_simple.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "warning"
    assert f.line == 1
    assert "not guarded" in f.message
    assert "total / count" in f.message


def test_sr041_unguarded_in_foreach_fires_warning() -> None:
    br = _load("div_unguarded_in_foreach.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].line == 2


def test_sr041_irrelevant_guard_fires_warning() -> None:
    """Guard mentions a different variable; doesn't establish
    anything about the divisor."""
    br = _load("div_unguarded_irrelevant_guard.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].line == 2


# ── Negative — KNOWN_NONZERO (silent) ─────────────────────────────


def test_sr041_then_of_ne_zero_silent() -> None:
    assert _sr041(_load("div_safe_ne_zero.smartrule")) == []


def test_sr041_then_of_gt_zero_silent() -> None:
    assert _sr041(_load("div_safe_gt_zero.smartrule")) == []


def test_sr041_then_of_lt_zero_silent() -> None:
    assert _sr041(_load("div_safe_lt_zero.smartrule")) == []


def test_sr041_then_of_ge_one_silent() -> None:
    """Boundary: ``y >= 1`` — N=1 > 0 → KNOWN_NONZERO. (``y >= 0``
    would be UNKNOWN since 0 is included.)"""
    assert _sr041(_load("div_safe_ge_one.smartrule")) == []


def test_sr041_then_of_truthy_silent() -> None:
    assert _sr041(_load("div_safe_truthy.smartrule")) == []


def test_sr041_then_of_value_engagement_silent() -> None:
    """``y = "ACTIVE"`` — equality to a non-empty string literal
    → KNOWN_NONZERO."""
    assert _sr041(_load("div_safe_value_engagement.smartrule")) == []


def test_sr041_literal_nonzero_silent() -> None:
    assert _sr041(_load("div_safe_literal_nonzero.smartrule")) == []


def test_sr041_call_rhs_silent() -> None:
    """Function-call divisor — conservative skip; can't reason about
    return values."""
    assert _sr041(_load("div_safe_call_rhs.smartrule")) == []


# ── Edge ──────────────────────────────────────────────────────────


def test_sr041_in_string_or_comment_silent() -> None:
    """Tokenizer drops comments and treats string literals as opaque.
    No ``BinaryOp("/")`` AST nodes exist for those texts."""
    assert _sr041(_load("div_in_string_or_comment.smartrule")) == []


# ── Real-pack regression ──────────────────────────────────────────


def test_sr041_compound_guard_currently_unknown_documented() -> None:
    """A compound ``and``/``or`` condition is currently treated as
    UNKNOWN — SR041 fires a warning even though each conjunct alone
    would establish KNOWN_NONZERO.

    This is conservative behavior, deliberately not "smart". A future
    refinement may classify each conjunct independently (e.g.
    ``y > 0 and z > 0`` would split into ``y > 0`` and ``z > 0``,
    each independently proving non-zero). Until that refinement
    lands, this test pins the current contract: the warning fires
    on the division, with the if-stack frame correctly classified
    as UNKNOWN.
    """
    br = _load("div_compound_guard.smartrule")
    findings = _sr041(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_sr041_real_pack_update_document_process_documented() -> None:
    br = _load("update_document_process.smartrule")
    findings = _sr041(br)
    for f in findings:
        assert f.severity in ("error", "warning")
        assert f.category == "logic"


def test_sr041_real_pack_compute_template_order_documented() -> None:
    br = _load("compute_template_order.smartrule")
    findings = _sr041(br)
    for f in findings:
        assert f.severity in ("error", "warning")
        assert f.category == "logic"


# ════════════════════════════════════════════════════════════════════
# SR042 — UnverifiedObjectCheck
# ════════════════════════════════════════════════════════════════════


def _sr042(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR042"]


# ── Positive — UNKNOWN (warning) ──────────────────────────────────


def test_sr042_unguarded_log_fires_warning() -> None:
    br = _load("unverified_unguarded_log.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "warning"
    assert f.category == "logic"
    assert f.line == 2
    assert "obj" in f.message
    assert "getObject" in f.message


def test_sr042_unguarded_assign_fires_warning() -> None:
    br = _load("unverified_unguarded_assign.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].line == 2
    assert "findRecord" in findings[0].message


def test_sr042_unguarded_chain_fires_warning() -> None:
    """``obj.first.NAME`` — the inner FieldAccess root is ``obj``;
    the use is detected on the outer chain and dedup'd on the inner.
    """
    br = _load("unverified_unguarded_chain.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].line == 2
    assert "getSqlData" in findings[0].message


def test_sr042_unguarded_method_fires_warning() -> None:
    """``obj.refresh()`` — Call.callee is FieldAccess(obj, refresh)."""
    br = _load("unverified_unguarded_method.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].line == 2


def test_sr042_table_selector_source_fires_warning() -> None:
    """``obj := other.TABLE[C = 1]`` — TableSelector RHS is also
    a fallible source (no row may match)."""
    br = _load("unverified_table_selector_source.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].line == 2
    assert "other.TABLE" in findings[0].message


# ── Positive — KNOWN_NULL (error) ─────────────────────────────────


def test_sr042_then_of_eq_null_fires_error() -> None:
    """``if (obj = null) { obj.F ... }`` — guard proves obj is null
    in the then-branch; dereference will crash."""
    br = _load("unverified_then_of_eq_null.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == "error"
    assert f.line == 3
    assert "null" in f.message.lower()


def test_sr042_else_of_ne_null_fires_error() -> None:
    """``if (obj != null) {} else { obj.F := v; }`` — else of presence
    check is the null branch."""
    br = _load("unverified_else_of_ne_null.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].line == 5


# ── Negative — KNOWN_PRESENT (silent) ─────────────────────────────


def test_sr042_then_of_ne_null_silent() -> None:
    assert _sr042(_load("unverified_then_of_ne_null.smartrule")) == []


def test_sr042_then_of_truthy_multiple_silent() -> None:
    """Multiple uses inside the same presence-guarded then-branch —
    all silent."""
    assert _sr042(_load("unverified_then_of_truthy_multiple.smartrule")) == []


def test_sr042_else_of_eq_null_silent() -> None:
    assert _sr042(_load("unverified_else_of_eq_null.smartrule")) == []


def test_sr042_value_engagement_silent() -> None:
    """``if (obj = "VALIDATED")`` — equality to a non-empty literal
    engages the value, implying presence."""
    assert _sr042(_load("unverified_value_engagement.smartrule")) == []


# ── Negative — non-fallible source (silent) ───────────────────────


def test_sr042_int_source_silent() -> None:
    """``obj := 5`` — integer, not in fallible sources."""
    assert _sr042(_load("unverified_int_silent.smartrule")) == []


def test_sr042_unknown_call_silent() -> None:
    """``obj := computeStuff()`` — callee not in
    FALLIBLE_OBJECT_SOURCES; silent."""
    assert _sr042(_load("unverified_unknown_source_silent.smartrule")) == []


def test_sr042_alias_direct_only_silent() -> None:
    """v1 limitation: ``y := x`` does not propagate fallibility.
    Use of y.F is silent even though x was fallible. Document
    the limitation; refine if needed."""
    assert _sr042(_load("unverified_alias_silent.smartrule")) == []


# ── Negative — dedup ──────────────────────────────────────────────


def test_sr042_dedup_silent_after_first_fire() -> None:
    """``log(obj.F); log(obj.G);`` — only the first use fires;
    same object, same risk class, already reported."""
    br = _load("unverified_dedup_silent.smartrule")
    findings = _sr042(br)
    assert len(findings) == 1
    assert findings[0].line == 2  # only the first use


# ── Edge ──────────────────────────────────────────────────────────


def test_sr042_in_string_or_comment_silent() -> None:
    """Tokenizer drops comments and treats string literals as opaque.
    No FieldAccess AST nodes exist for those texts."""
    assert _sr042(_load("unverified_in_string_or_comment.smartrule")) == []


def test_sr042_foreach_var_silent() -> None:
    """``foreach x in some_list`` — x is loop-introduced, not from a
    fallible AssignStmt. Silent by construction."""
    assert _sr042(_load("unverified_foreach_var_silent.smartrule")) == []


# ── Real-pack regression ──────────────────────────────────────────


def test_sr042_real_pack_update_document_process_documented() -> None:
    """Document SR042 findings on the real script.

    UPDATE_DOCUMENT_PROCESS uses ``getObject``, ``findRecord`` and
    similar fallible built-ins extensively; any findings are genuine
    risk sites worth reviewing.
    """
    br = _load("update_document_process.smartrule")
    findings = _sr042(br)
    for f in findings:
        assert f.severity in ("warning", "error")
        assert f.category == "logic"


def test_sr042_real_pack_compute_template_order_documented() -> None:
    br = _load("compute_template_order.smartrule")
    findings = _sr042(br)
    for f in findings:
        assert f.severity in ("warning", "error")
        assert f.category == "logic"

