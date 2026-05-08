"""Tests for logic checks (SR021 DeadCodeCheck)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# Importing the package triggers @register_check for every check.
from reviewer import checks as _checks  # noqa: F401
from reviewer.engine.runner import run_review
from reviewer_legacy import check_dead_code


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
    """Return the set of terminator lines flagged by the AST check.

    Convention: ``Finding.line`` points at the terminator, matching the
    legacy ``check_dead_code`` output (so the diff-test compares like
    with like).
    """
    return {
        f.line for f in run_review(br).findings if f.rule_id == "SR021"
    }


# Legacy messages look like:
#   "Dead code after terminator 'return' at line 22: <next>"
_LEGACY_TERM_LINE_RE = re.compile(r"at line (\d+):")


def _legacy_sr021_terminator_lines(br: FakeBizRule) -> set[int]:
    """Lines on which legacy *saw* a terminator that triggered a finding."""
    out: set[int] = set()
    for issue in check_dead_code(br.script):
        m = _LEGACY_TERM_LINE_RE.search(issue)
        if m:
            out.add(int(m.group(1)))
    return out


# ── Positive ─────────────────────────────────────────────────────────


def test_sr021_positive_flags_terminator_line() -> None:
    br = _load("dead_code_after_return.smartrule")
    # The return is on line 6; the dead msginfo on line 7. Finding.line
    # follows the legacy convention and points at the terminator (6).
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
    """The legacy regex matched ``return``/``abort``/``skip`` literals
    inside comments and string literals, producing false positives.
    The AST pipeline tokenizes strings as opaque tokens and discards
    comments, so this whole class of false positive is gone.
    """
    br = _load("dead_code_in_string_or_comment.smartrule")
    assert _ast_sr021_terminator_lines(br) == set()


def test_sr021_does_not_flag_else_branch_after_return_in_if() -> None:
    """Legacy false positive: ``if (x) { return; } else { ... }`` was
    flagged because the legacy line-scanner sees ``return`` then a non-
    ``}`` line (the ``else`` block contents). The AST check recognises
    that the return lives inside the then-branch's own Block, so the
    else-branch — and any code after the whole if — is reachable.
    """
    br = _load("dead_code_if_else_legacy_fp.smartrule")
    assert _ast_sr021_terminator_lines(br) == set()


# ── Diff-test: AST findings ⊆ legacy findings ───────────────────────


def test_sr021_clean_fixture_strict_agreement() -> None:
    """On a script with no terminators at all, both pipelines must
    return exactly the empty set — strictest possible agreement.
    """
    br = _load("dead_code_clean.smartrule")
    assert (
        _ast_sr021_terminator_lines(br)
        == _legacy_sr021_terminator_lines(br)
        == set()
    )


@pytest.mark.parametrize(
    "fixture_name",
    [
        # Real positive: legacy also fires on `return` inside a comment
        # on line 1, which the AST correctly suppresses.
        "dead_code_after_return.smartrule",
        # Comments/strings: legacy false-positives, AST silent.
        "dead_code_in_string_or_comment.smartrule",
        # if/else legacy FP: legacy emits, AST silent.
        "dead_code_if_else_legacy_fp.smartrule",
        # Real fixtures: legacy emits a mix of true and false positives.
        "update_document_process.smartrule",
        "compute_template_order.smartrule",
    ],
)
def test_sr021_ast_lines_are_subset_of_legacy(fixture_name: str) -> None:
    """The AST check must not regress recall: every line it flags must
    also be flagged by legacy. Legacy may flag *more* lines — those are
    legacy false positives that the AST pipeline correctly suppresses
    (comments, strings, if/else artifacts, brace de-sync).
    """
    br = _load(fixture_name)
    ast_lines = _ast_sr021_terminator_lines(br)
    legacy_lines = _legacy_sr021_terminator_lines(br)
    assert ast_lines <= legacy_lines, (
        f"AST flagged terminator lines {ast_lines - legacy_lines} that "
        f"legacy did not — recall regression."
    )


# ════════════════════════════════════════════════════════════════════
# SR020 StaticConditionCheck
# ════════════════════════════════════════════════════════════════════

from reviewer_legacy import check_static_conditions  # noqa: E402


_LEGACY_SR020_LINE_RE = re.compile(r"at line (\d+):")


def _ast_sr020_lines(br: FakeBizRule) -> set[int]:
    return {f.line for f in run_review(br).findings if f.rule_id == "SR020"}


def _legacy_sr020_lines(br: FakeBizRule) -> set[int]:
    out: set[int] = set()
    for issue in check_static_conditions(br.script):
        m = _LEGACY_SR020_LINE_RE.search(issue)
        if m:
            out.add(int(m.group(1)))
    return out


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
    """Legacy regex `\\bif\\s*\\(...\\)` matches inside comments and
    string literals, so it (wrongly) flags `// if (1 = 1)` and
    `msg := "if (1 = 1)"`. The AST pipeline never sees comments, and
    string literals are opaque tokens — both classes of false positive
    disappear.
    """
    br = _load("static_cond_in_string_or_comment.smartrule")
    assert _ast_sr020_lines(br) == set()


# ── AST-only: structural improvements over the regex form ──────────


def test_sr020_ast_only_self_compare_field_access() -> None:
    """`obj.F = obj.F` — legacy compares the literal text on each side,
    but its split-by-operator + strip dance is fragile (any whitespace
    or sub-expression difference breaks it). The AST walks two
    `FieldAccess` trees and reports them as structurally equal.
    """
    br = _load("static_cond_self_field.smartrule")
    assert _ast_sr020_lines(br) == {2}


def test_sr020_ast_only_self_compare_call() -> None:
    """`f(x) = f(x)` — text-equality happens to work for legacy here,
    but the AST proves the property structurally (same callee, same
    args), which generalises to `f(a, b) = f(a, b)`, etc.
    """
    br = _load("static_cond_self_call.smartrule")
    assert _ast_sr020_lines(br) == {2}


def test_sr020_ast_only_trivial_subcondition() -> None:
    """`1 = 1 and x` — legacy splits the condition at the FIRST operator
    it finds, sees `1 and x` on the right, gives up, and emits nothing.
    The AST recurses through `and`/`or` and catches the dead `1 = 1`.
    Severity: error — leftover debug code is loud, not redeemed by the
    live conjunct.
    """
    br = _load("static_cond_trivial_sub.smartrule")
    findings = [
        f for f in run_review(br).findings if f.rule_id == "SR020"
    ]
    assert {f.line for f in findings} == {2}
    assert all(f.severity == "error" for f in findings)


def test_sr020_ast_only_parens_are_transparent() -> None:
    """`(x) = x` — legacy's text split sees ` (x) ` vs ` x `, decides
    they're not equal, and stays silent. The AST parser drops the
    redundant parens, so structural equality still fires.
    """
    br = _load("static_cond_parens.smartrule")
    assert _ast_sr020_lines(br) == {2}


# ── Diff-test: AST findings ⊆ legacy findings ──────────────────────
#
# Excluded fixtures (AST flags lines legacy MISSES, by design):
#   - static_cond_self_field.smartrule  (legacy can't structurally eq)
#   - static_cond_self_call.smartrule   (legacy's `(.*?)` truncates at
#                                        the first `)`, so it never
#                                        sees `f(x) = f(x)`)
#   - static_cond_trivial_sub.smartrule (legacy splits at first `=`,
#                                        misses the dead conjunct)
#   - static_cond_parens.smartrule      (legacy text-split breaks)
#   - update_document_process.smartrule (real-world: `f(a) = f(a) and
#                                        f(a) = f(a)` — both legacy
#                                        weaknesses combined)
# These represent the AST pipeline's *improvements*, asserted by their
# own dedicated tests above.


@pytest.mark.parametrize(
    "fixture_name",
    [
        "static_cond_literal_eq.smartrule",
        "static_cond_dynamic.smartrule",
        "static_cond_in_string_or_comment.smartrule",
        "compute_template_order.smartrule",
    ],
)
def test_sr020_ast_lines_are_subset_of_legacy(fixture_name: str) -> None:
    """For real-world fixtures, AST recall must not exceed legacy:
    every line the AST flags must also be flagged by legacy. Legacy
    over-flags on comments and strings — those are legacy FPs the AST
    correctly suppresses, hence the strict subset relation.
    """
    br = _load(fixture_name)
    ast_lines = _ast_sr020_lines(br)
    legacy_lines = _legacy_sr020_lines(br)
    assert ast_lines <= legacy_lines, (
        f"AST flagged lines {ast_lines - legacy_lines} that legacy did "
        f"not — recall regression on {fixture_name}."
    )
