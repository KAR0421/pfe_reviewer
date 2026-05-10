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

