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
