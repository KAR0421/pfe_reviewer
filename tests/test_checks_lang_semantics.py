"""Tests for language-semantics checks (SR059 UnusedVariableCheck)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Importing the module triggers @register_check.
from reviewer.checks import lang_semantics  # noqa: F401
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


def _sr059(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR059"]


# ── SR059 Positive ─────────────────────────────────────────────────


def test_sr059_simple_unused_fires() -> None:
    br = _load("unused_var_simple.smartrule")
    findings = _sr059(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 4  # ``temp := 42;`` is on line 4
    assert f.severity == "info"
    assert f.category == "lang"
    assert "temp" in f.message
    assert "never read" in f.message


def test_sr059_typo_on_read_side_fires_on_original() -> None:
    """Real-world motivating example: typo on the read side leaves the
    original assignment unused. ``total`` is assigned, ``totl`` is
    read — only ``total`` is reported (``totl`` was never assigned)."""
    br = _load("unused_var_typo_on_read.smartrule")
    findings = _sr059(br)
    assert len(findings) == 1
    assert findings[0].line == 4  # ``total := arg1 + arg2;``
    assert "total" in findings[0].message


def test_sr059_cond_assign_form_fires() -> None:
    """``?=`` is an assignment for SR059 purposes — purely an assign,
    no reading semantics."""
    br = _load("unused_var_cond_assign.smartrule")
    findings = _sr059(br)
    assert len(findings) == 1
    assert "flag" in findings[0].message


# ── SR059 Negative ─────────────────────────────────────────────────


def test_sr059_all_used_silent() -> None:
    br = _load("unused_var_all_used.smartrule")
    assert _sr059(br) == []


def test_sr059_multi_assign_one_read_silent() -> None:
    """One read of ``count`` silences all three assignments to it."""
    br = _load("unused_var_multi_assign_one_read.smartrule")
    assert _sr059(br) == []


def test_sr059_counter_for_loop_var_excluded() -> None:
    """Per policy, ``for i := 1 to 10`` introduces ``i`` as a loop
    control variable — it is never reported as unused even when the
    body doesn't reference it."""
    br = _load("unused_var_counter_for.smartrule")
    assert _sr059(br) == []


def test_sr059_foreach_loop_var_excluded() -> None:
    """``foreach item in items`` introduces ``item`` — excluded.
    Meanwhile ``items`` IS read by the foreach iterable, so it does
    not fire either."""
    br = _load("unused_var_foreach.smartrule")
    assert _sr059(br) == []


def test_sr059_field_assignment_target_not_a_variable() -> None:
    """``obj.READY := 1`` is a field write, not a bare-variable
    assignment. The target is not a candidate; the receiver ``obj``
    is a read of the local."""
    br = _load("unused_var_field_assign.smartrule")
    assert _sr059(br) == []


# ── SR059 Edge: strings, comments, method calls ────────────────────


def test_sr059_ignores_assignments_in_strings_and_comments() -> None:
    """``zombie := 0`` appears in both a string literal and a comment.
    The tokenizer drops the comment and treats the string as opaque,
    so the AST never sees ``zombie`` as an assignment."""
    br = _load("unused_var_in_string_or_comment.smartrule")
    assert _sr059(br) == []


def test_sr059_method_call_receiver_counts_as_read() -> None:
    """``obj.update(arg)`` reads both ``obj`` (the receiver chain) and
    ``arg`` (the call argument). Neither must be reported as unused."""
    br = _load("unused_var_method_call.smartrule")
    assert _sr059(br) == []


# ── SR059 Real-pack regression ─────────────────────────────────────
#
# These two fixtures are real BizRule scripts copied from
# ``sample.pack`` / ``sample2.pack``. Their SR059 findings are
# documented here so any future change that alters the read/assignment
# walker is caught by an obvious diff in expected output.


def test_sr059_real_pack_update_document_process() -> None:
    """``update_document_process.smartrule`` (sample.pack).

    Documented findings: seven local variables are assigned but never
    read. The block at lines 5–12 sets up state for the rest of the
    rule, but the rule actually returns on line 20 and the trailing
    code (assignments + nested foreach) writes to locals nothing else
    reads. All seven are real defects in the source — the regression
    test pins them.
    """
    br = _load("update_document_process.smartrule")
    findings = _sr059(br)
    reported = {f.message.split("'")[1] for f in findings}
    assert reported == {
        "contribManagement",
        "validFlag",
        "inValidFlag",
        "levelSdg",
        "existe",
        "tmpCheck",
        "tmpLoop",
    }
    # All emitted at info severity, category lang.
    assert all(f.severity == "info" and f.category == "lang" for f in findings)


def test_sr059_real_pack_compute_template_order() -> None:
    """``compute_template_order.smartrule`` (sample2.pack).

    Documented findings: seven unused locals. Notably ``reportDefId``
    is flagged because the only "read" site is itself an assignment
    (``reportDefId := reportData.DEF;``) — SR059 by design treats
    assignment targets as writes, not reads. ``effectDate`` is
    similar: assigned at line 22 and reassigned at line 24, with no
    intervening or following read.
    """
    br = _load("compute_template_order.smartrule")
    findings = _sr059(br)
    reported = {f.message.split("'")[1] for f in findings}
    assert reported == {
        "reportDefId",
        "reportDoc",
        "listToDelete",
        "pfCode",
        "repDate",
        "jurisdictionId",
        "effectDate",
    }


# ════════════════════════════════════════════════════════════════════
# SR057 — CaseTypoVariableCheck
# ════════════════════════════════════════════════════════════════════

def _sr057(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR057"]


# ─── Positive ────────────────────────────────────────────────────────

def test_sr057_both_assigned_fires() -> None:
    """Canonical case: both ``contrib`` and ``Contrib`` are assigned
    in the same rule. Two distinct variables; almost certainly a
    typo.
    """
    br = _load("case_typo_both_assigned.smartrule")
    findings = _sr057(br)
    assert len(findings) == 1
    f = findings[0]
    # First occurrence of either spelling — ``contrib`` on line 4.
    assert f.line == 4
    assert f.severity == "info"
    assert f.category == "lang"
    assert "'Contrib'" in f.message
    assert "'contrib'" in f.message
    assert "case-typo" in f.message.lower()


def test_sr057_assigned_vs_read_fires() -> None:
    """``total`` is assigned, ``Total`` is only read downstream — the
    read picked up a phantom variable. Must fire.
    """
    br = _load("case_typo_assigned_vs_read.smartrule")
    findings = _sr057(br)
    assert len(findings) == 1
    assert findings[0].line == 4  # ``total`` on line 4


def test_sr057_nested_assignment_still_paired() -> None:
    """The assignment ``counter := counter + 1;`` lives inside an
    if → foreach → try; the read ``log(Counter)`` is at top level.
    The whole-script walk must still pair them.
    """
    br = _load("case_typo_nested_assignment.smartrule")
    findings = _sr057(br)
    assert len(findings) == 1
    # First occurrence of either spelling sits inside the try, on
    # the line of ``counter := counter + 1;`` (line 7).
    assert findings[0].line == 7
    assert "'Counter'" in findings[0].message
    assert "'counter'" in findings[0].message


# ─── Negative ────────────────────────────────────────────────────────

def test_sr057_neither_assigned_silent() -> None:
    """Both ``STATUS`` and ``Status`` are read-only — likely external
    constants, not local variables. Out of scope; must not fire.
    """
    br = _load("case_typo_neither_assigned.smartrule")
    assert _sr057(br) == []


def test_sr057_single_spelling_silent() -> None:
    """Only one spelling exists. No collision possible."""
    br = _load("case_typo_clean_single_spelling.smartrule")
    assert _sr057(br) == []


def test_sr057_callee_vs_variable_silent() -> None:
    """``compute(Compute)``: the callee ``compute`` is excluded from
    occurrences (function names are not variables). Only the local
    ``Compute`` remains — no collision.
    """
    br = _load("case_typo_callee_vs_variable.smartrule")
    assert _sr057(br) == []


# ─── Edge: comments and string literals ──────────────────────────────

def test_sr057_ignores_strings_and_comments() -> None:
    """Identifier-like text inside comments and string literals does
    not produce AST identifiers, so no spurious collision.
    """
    br = _load("case_typo_in_string_or_comment.smartrule")
    assert _sr057(br) == []


# ─── Real-pack regression ────────────────────────────────────────────
# Both real-pack fixtures are clean baselines for SR057. The
# `compute_template_order.smartrule` fixture has
# `reportData.P_VALUE[P_NAME='effectDate']` and a local `p_name`,
# but `P_NAME` is the LHS of `=` inside a `TableSelector.condition`
# — the column-context exclusion (see `_collect_case`) treats it as
# a column name, not a variable, so SR057 stays silent.

def test_sr057_real_pack_update_document_process_silent() -> None:
    br = _load("update_document_process.smartrule")
    assert _sr057(br) == []


def test_sr057_real_pack_compute_template_order_silent() -> None:
    br = _load("compute_template_order.smartrule")
    assert _sr057(br) == []



# ════════════════════════════════════════════════════════════════════
# SR055 — ArrayAliasCheck
# ════════════════════════════════════════════════════════════════════


def _sr055(br: FakeBizRule):
    return [f for f in run_review(br).findings if f.rule_id == "SR055"]


# ── SR055 Positive (fires) ─────────────────────────────────────────


def test_sr055_simple_alias_then_mutation_fires() -> None:
    br = _load("array_alias_simple_mutation.smartrule")
    findings = _sr055(br)
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 2  # the alias line
    assert f.severity == "warning"
    assert f.category == "lang"
    assert "'b := a'" in f.message
    assert "line 3" in f.message  # mutation line referenced
    assert "arraycopy(a)" in f.message


def test_sr055_source_mutation_after_alias_fires() -> None:
    """The mutation may be on the *source* (a) rather than the alias
    (b) — either side counts."""
    br = _load("array_alias_source_mutation.smartrule")
    findings = _sr055(br)
    assert len(findings) == 1
    assert findings[0].line == 2


def test_sr055_transitive_chain_fires_on_inner_alias() -> None:
    """ := arrayremove(a, 1) makes  array-typed; c := b is
    then an alias candidate. Mutation through c[0] := 99 fires on
    the c := b line, not on  := arrayremove(...) (which is a
    Call RHS and not the alias pattern).
    """
    br = _load("array_alias_transitive_chain.smartrule")
    findings = _sr055(br)
    assert len(findings) == 1
    assert findings[0].line == 3  # the c := b line
    assert "'c := b'" in findings[0].message


# ── SR055 Negative (silent) ────────────────────────────────────────


def test_sr055_arraycopy_rhs_silent() -> None:
    """The documented correct pattern:  := arraycopy(a)."""
    br = _load("array_alias_arraycopy_silent.smartrule")
    assert _sr055(br) == []


def test_sr055_alias_without_mutation_silent() -> None:
    """An alias with no later mutation may be deliberate (just a
    different name for the same array). Don't report."""
    br = _load("array_alias_no_mutation_silent.smartrule")
    assert _sr055(br) == []


def test_sr055_foreach_iterable_read_silent() -> None:
    """oreach x in b do { ... } reads , doesn't mutate it."""
    br = _load("array_alias_foreach_read_silent.smartrule")
    assert _sr055(br) == []


def test_sr055_non_array_rhs_silent() -> None:
    """ is an integer;  := a is not an array alias. Not in
    scope, no finding even though  is later re-assigned."""
    br = _load("array_alias_non_array_rhs_silent.smartrule")
    assert _sr055(br) == []


def test_sr055_arraysize_returns_int_silent() -> None:
    """
 := arraysize(a) makes 
 an integer (arraysize returns
    int, not an array).  := n is therefore not an array alias.
    """
    br = _load("array_alias_arraysize_int_silent.smartrule")
    assert _sr055(br) == []


def test_sr055_call_rhs_not_an_alias_silent() -> None:
    """ := arrayunion(a, otherArr) makes  array-typed but is
    a Call, not the alias pattern. Even with a later mutation
    [0] := 99, no finding."""
    br = _load("array_alias_call_rhs_silent.smartrule")
    assert _sr055(br) == []


# ── SR055 Edge ─────────────────────────────────────────────────────


def test_sr055_in_string_or_comment_silent() -> None:
    """Tokenizer drops comments and treats string literals as opaque.
    The AST never sees the  := a text inside them."""
    br = _load("array_alias_in_string_or_comment.smartrule")
    assert _sr055(br) == []


def test_sr055_loop_var_excluded_silent() -> None:
    """oreach b in a introduces  as a loop variable, excluded
    from alias bookkeeping. No finding."""
    br = _load("array_alias_loop_var_silent.smartrule")
    assert _sr055(br) == []


# ── SR055 Real-pack regression ─────────────────────────────────────


def test_sr055_real_pack_update_document_process_documented() -> None:
    br = _load("update_document_process.smartrule")
    findings = _sr055(br)
    for f in findings:
        assert f.severity == "warning"
        assert f.category == "lang"


def test_sr055_real_pack_compute_template_order_documented() -> None:
    br = _load("compute_template_order.smartrule")
    findings = _sr055(br)
    for f in findings:
        assert f.severity == "warning"
        assert f.category == "lang"
