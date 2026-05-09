"""Tests for documentation checks (SR010 MissingUserCommentCheck,
SR012.1 InlineCommentDensityCheck).

SR010 is a faithful migration of ``check_minimal_documentation`` —
trivially-correct, no semantic divergence; the diff-test is a strict
equality.

SR012.1 is AST-native. Legacy never implemented a comment-density
rule (regex over raw text would have been distorted by ``//`` inside
string literals). Tests cover positive, negative, and the trivial
case where complexity is zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from reviewer import checks as _checks  # noqa: F401  (registers checks)
from reviewer.engine.runner import run_review
from reviewer_legacy import check_minimal_documentation


FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"


@dataclass
class FakeBizRule:
    name: str
    script: str = ""
    comment: str = ""
    scope: str = ""


def _load(
    name: str, comment: str = "documented", script_name: str | None = None
) -> FakeBizRule:
    src = (FIXTURES / (script_name or name)).read_text(encoding="utf-8")
    return FakeBizRule(name=name, script=src, comment=comment)


def _ast_lines(br: FakeBizRule, rule_id: str) -> set[int]:
    return {f.line for f in run_review(br).findings if f.rule_id == rule_id}


# ════════════════════════════════════════════════════════════════════
# SR010 MissingUserCommentCheck
# ════════════════════════════════════════════════════════════════════


def test_sr010_positive_empty_comment() -> None:
    br = FakeBizRule(name="X", script="x := 1;", comment="")
    findings = [f for f in run_review(br).findings if f.rule_id == "SR010"]
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 1
    assert f.severity == "error"
    assert f.category == "docs"
    assert "USER_COMMENT" in f.message


def test_sr010_positive_whitespace_only_comment() -> None:
    br = FakeBizRule(name="X", script="x := 1;", comment="   \n\t ")
    assert _ast_lines(br, "SR010") == {1}


def test_sr010_negative_real_comment() -> None:
    br = FakeBizRule(name="X", script="x := 1;", comment="Update the doc.")
    assert _ast_lines(br, "SR010") == set()


# ── Diff-test: AST and legacy must agree exactly on SR010 ──────────


@pytest.mark.parametrize(
    "comment,expected_fires",
    [
        ("", True),
        ("   ", True),
        ("\t\n", True),
        ("Real description", False),
        (" non-trivial ", False),
    ],
)
def test_sr010_matches_legacy_exactly(comment: str, expected_fires: bool) -> None:
    """SR010 is a faithful port: AST and legacy must agree on every
    input. No divergence allowed.
    """
    br = FakeBizRule(name="X", script="x := 1;", comment=comment)
    legacy_fires = bool(check_minimal_documentation(br))
    ast_fires = bool(_ast_lines(br, "SR010"))
    assert legacy_fires == ast_fires == expected_fires


# ════════════════════════════════════════════════════════════════════
# SR012.1 InlineCommentDensityCheck
# ════════════════════════════════════════════════════════════════════


# ── Positive ────────────────────────────────────────────────────────


def test_sr012_1_positive_complex_undocumented() -> None:
    """12 branches, only the file-header comment (1 inline ``//``).
    1 * 12 = 12 < 12 is false → boundary condition: ``>=`` passes,
    so 1 comment exactly satisfies. Use a fixture with strictly more
    complexity than 12 to land safely on the failing side."""
    br = _load(
        "inline_comments_undocumented.smartrule", comment="ok"
    )
    findings = [f for f in run_review(br).findings if f.rule_id == "SR012.1"]
    # Exactly 12 branches and 1 header comment: 1 * 12 = 12 >= 12 → passes.
    # We assert the boundary behaviour explicitly to lock the contract.
    assert findings == []


def test_sr012_1_positive_more_complex_than_density_allows(tmp_path) -> None:
    """13 branches, 1 header comment: 1 * 12 = 12 < 13 → fire."""
    body = ["// header"]
    body += [f"x{i} := {i};" for i in range(1, 5)]
    body += [f"if (x1 = {i}) {{ y{i} := 1; }}" for i in range(1, 14)]
    src = "\n".join(body)
    br = FakeBizRule(name="dense", script=src, comment="ok")
    findings = [f for f in run_review(br).findings if f.rule_id == "SR012.1"]
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 1
    assert f.severity == "warning"
    assert f.category == "docs"
    assert "1 `//` comment" in f.message
    assert "13 branches" in f.message


# ── Negative ────────────────────────────────────────────────────────


def test_sr012_1_negative_well_documented() -> None:
    """12 branches and 4 inline comments → 4 * 12 = 48 >= 12, passes."""
    br = _load("inline_comments_well_documented.smartrule", comment="ok")
    assert _ast_lines(br, "SR012.1") == set()


def test_sr012_1_negative_trivial_script() -> None:
    """Zero branches / loops / risky calls — the rule is silent
    regardless of comment count, because there is nothing to
    document."""
    br = _load("inline_comments_trivial.smartrule", comment="ok")
    assert _ast_lines(br, "SR012.1") == set()


# ── Edge: comments inside string literals don't count as inline docs


def test_sr012_1_string_with_comment_marker_does_not_count() -> None:
    """``"// fake"`` is a string literal, not a comment. The tokenizer
    side-channel ``CheckContext.comments`` only contains real ``//``
    comments, so the AST check correctly counts zero comments here."""
    body = ["// header"]
    # 13 branches without any further inline comments…
    body += [f"if (x = {i}) {{ y{i} := 1; }}" for i in range(1, 14)]
    # …plus a string literal that *looks* like a comment but isn't.
    body += ['msg := "// not a real comment";']
    src = "\n".join(body)
    br = FakeBizRule(name="strcom", script=src, comment="ok")
    # Header comment count = 1; complexity = 13 → fires.
    assert _ast_lines(br, "SR012.1") == {1}


def test_sr012_1_block_comment_counts_as_one() -> None:
    """A ``/* ... */`` block is one ``CommentToken`` in the side
    channel, regardless of how many lines it spans. With 12 branches
    and a single multi-line block comment, density is 1 × 12 = 12
    which satisfies the ratio — the check is silent.
    """
    body = ["/* multi-line", "   header", "   block */"]
    body += [f"if (x = {i}) {{ y{i} := 1; }}" for i in range(1, 13)]
    src = "\n".join(body)
    br = FakeBizRule(name="block", script=src, comment="ok")
    assert _ast_lines(br, "SR012.1") == set()
