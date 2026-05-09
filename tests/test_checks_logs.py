"""Tests for log checks (SR090 VerboseLogInLoopCheck, SR091 TooFewLogsCheck).

Both checks were migrated from the single ``check_logs`` function in
``reviewer_legacy``. SR091 was also *redesigned* in the AST version —
the legacy threshold (``len(lines) > 50 and num_logs < 3``) is a
heuristic over physical lines and substring matches; the AST rule
talks about log density relative to *complexity* (branches, loops,
risky calls). Diff-tests therefore separate "recall preservation"
from "intentional reformulation".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from reviewer import checks as _checks  # noqa: F401  (registers checks)
from reviewer.engine.runner import run_review
from reviewer_legacy import check_logs


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


# Legacy SR090 message: "Verbose log detected inside loop at line N: ..."
# Legacy SR091 message: "Complex script (N lines) has too few logs (M)"
_LEGACY_SR090_LINE_RE = re.compile(r"Verbose log detected inside loop at line (\d+):")
_LEGACY_SR091_RE = re.compile(r"Complex script \(\d+ lines\) has too few logs")


def _ast_lines(br: FakeBizRule, rule_id: str) -> set[int]:
    return {
        f.line for f in run_review(br).findings if f.rule_id == rule_id
    }


def _legacy_sr090_lines(br: FakeBizRule) -> set[int]:
    out: set[int] = set()
    for issue in check_logs(br.script):
        m = _LEGACY_SR090_LINE_RE.search(issue)
        if m:
            out.add(int(m.group(1)))
    return out


def _legacy_sr091_fires(br: FakeBizRule) -> bool:
    return any(_LEGACY_SR091_RE.search(i) for i in check_logs(br.script))


# ════════════════════════════════════════════════════════════════════
# SR090 VerboseLogInLoopCheck
# ════════════════════════════════════════════════════════════════════


# ── Positive ────────────────────────────────────────────────────────


def test_sr090_positive_simple_loop_log() -> None:
    br = _load("verbose_log_in_loop_simple.smartrule")
    # `msginfo` is on line 4 of the fixture.
    assert _ast_lines(br, "SR090") == {4}


def test_sr090_positive_metadata() -> None:
    br = _load("verbose_log_in_loop_simple.smartrule")
    sr090 = [f for f in run_review(br).findings if f.rule_id == "SR090"]
    assert len(sr090) == 1
    f = sr090[0]
    assert f.severity == "warning"
    assert f.category == "logs"
    assert "msginfo" in f.message


# ── Negative ────────────────────────────────────────────────────────


def test_sr090_negative_log_outside_loop() -> None:
    br = _load("verbose_log_no_loop.smartrule")
    assert _ast_lines(br, "SR090") == set()


# ── Edge: comments and string literals ─────────────────────────────


def test_sr090_ignores_loop_keyword_in_comment_and_string() -> None:
    """Legacy regex matches ``foreach`` inside a comment line and
    ``msginfo`` inside a string literal — both fire false positives.
    The AST tokenizer drops comments and tokenizes strings as opaque
    tokens, so neither is visible to the check.
    """
    br = _load("verbose_log_in_string_or_comment.smartrule")
    assert _ast_lines(br, "SR090") == set()


# ── AST-only improvements ──────────────────────────────────────────


def test_sr090_ast_only_reports_every_log_in_loop() -> None:
    """Legacy "warns once per loop" — it resets ``inside_loop`` after
    the first match. Three log calls in the same loop body therefore
    produce one finding instead of three. The AST queries the loop
    stack on every call site, so all three lines fire.
    """
    br = _load("verbose_log_in_loop_multiple.smartrule")
    assert _ast_lines(br, "SR090") == {5, 6, 7}


def test_sr090_ast_only_does_not_flag_logs_after_loop_closes() -> None:
    """Legacy never clears ``inside_loop``, so a log after the loop's
    closing brace is still reported as in-loop. The AST loop stack
    pops correctly when the body's ``Block`` ends.
    """
    br = _load("verbose_log_after_loop_closes.smartrule")
    assert _ast_lines(br, "SR090") == set()


# ── Diff-test: AST findings ⊆ legacy findings (with documented gaps)
#
# `verbose_log_in_loop_multiple.smartrule` is excluded — AST flags
# three lines, legacy flags one. That's the recall improvement
# asserted by ``test_sr090_ast_only_reports_every_log_in_loop``.


@pytest.mark.parametrize(
    "fixture_name",
    [
        "verbose_log_in_loop_simple.smartrule",
        "verbose_log_no_loop.smartrule",
        "verbose_log_in_string_or_comment.smartrule",
        "verbose_log_after_loop_closes.smartrule",
        "update_document_process.smartrule",
        "compute_template_order.smartrule",
    ],
)
def test_sr090_ast_lines_are_subset_of_legacy(fixture_name: str) -> None:
    """The AST check must not regress recall: every line it flags must
    also be flagged by legacy. Legacy may flag *more* lines — those are
    legacy false positives the AST correctly suppresses (comments,
    strings, post-loop logs the legacy never reset the flag for).
    """
    br = _load(fixture_name)
    ast = _ast_lines(br, "SR090")
    legacy = _legacy_sr090_lines(br)
    assert ast <= legacy, (
        f"AST flagged lines {ast - legacy} that legacy did not — "
        f"recall regression on {fixture_name}."
    )


# ════════════════════════════════════════════════════════════════════
# SR091 TooFewLogsCheck
# ════════════════════════════════════════════════════════════════════
#
# SR091 is a *reformulation*, not a port. Legacy fires on
# ``len(lines) > 50 and num_logs < 3`` — physical lines, substring
# count. AST fires on ``stmts > 50 and logs * 5 < complexity`` where
# complexity = branches + loops + risky_calls. The two rules answer
# different questions, so the legacy reference is used only for the
# specific cases where they happen to agree (positive on a script
# that legacy would also flag), not as a global subset contract.


# ── Positive ────────────────────────────────────────────────────────


def test_sr091_positive_complex_undocumented() -> None:
    """60 statements, 1 log call, 12 branches → complexity 12, ratio
    requires logs >= 12/5 = 2.4. One log is insufficient, fire."""
    br = _load("too_few_logs_complex.smartrule")
    findings = [f for f in run_review(br).findings if f.rule_id == "SR091"]
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 1
    assert f.severity == "info"
    assert f.category == "logs"
    # Message must explain the trip — counts surface in the text. We
    # assert structure ("a number above the threshold of statements,
    # one log call, and a complexity count is mentioned"), not exact
    # numbers, because the statement counter's treatment of comments
    # and blank lines is an implementation detail.
    m = re.search(r"\((\d+) statements\)", f.message)
    assert m is not None, f"message missing '(N statements)': {f.message!r}"
    assert int(m.group(1)) > 50
    assert "1 log call" in f.message
    assert re.search(r"\d+ branches/loops/risky calls", f.message), (
        f"message missing complexity count: {f.message!r}"
    )


# ── Negative ────────────────────────────────────────────────────────


def test_sr091_negative_short_script() -> None:
    """30 statements is below the long-script threshold; we don't
    require logs from short scripts regardless of their complexity.
    """
    br = _load("too_few_logs_short.smartrule")
    assert _ast_lines(br, "SR091") == set()


def test_sr091_negative_long_but_no_complexity() -> None:
    """60 statements, but every statement is a plain assignment.
    Zero branches, zero loops, zero risky calls → nothing to debug,
    no logs needed.
    """
    br = _load("too_few_logs_long_simple.smartrule")
    assert _ast_lines(br, "SR091") == set()


def test_sr091_negative_well_logged_complex_script() -> None:
    """60+ statements, 12 branches, 5 logs. 5 * 5 = 25 >= 12 →
    adequate density; observability is fine.
    """
    br = _load("too_few_logs_well_logged.smartrule")
    assert _ast_lines(br, "SR091") == set()


# ── AST-only reformulation ─────────────────────────────────────────


def test_sr091_ast_only_long_simple_script_not_flagged_unlike_legacy() -> None:
    """``too_few_logs_long_simple.smartrule`` is 60+ physical lines
    with zero log calls — legacy fires (line count > 50, log count < 3).
    The AST sees zero complexity and stays silent: a straight-line
    script needs no diagnostics. This is intentional divergence.
    """
    br = _load("too_few_logs_long_simple.smartrule")
    assert _legacy_sr091_fires(br) is True
    assert _ast_lines(br, "SR091") == set()


def test_sr091_ast_only_well_logged_complex_script_not_flagged() -> None:
    """``too_few_logs_well_logged.smartrule`` has 5 log calls — legacy
    is happy (5 >= 3). The AST is also happy because 5 logs cover the
    12 complex constructs at the required density. Both pipelines
    silent here, but for *different* reasons; this guards against the
    AST fixing the legacy threshold and accidentally re-flagging it.
    """
    br = _load("too_few_logs_well_logged.smartrule")
    assert _legacy_sr091_fires(br) is False
    assert _ast_lines(br, "SR091") == set()


def test_sr091_ast_only_complex_script_diverges_from_legacy_count() -> None:
    """The complex fixture is short enough in physical lines that the
    legacy 50-line threshold may or may not trip depending on
    formatting. Independent of legacy, the AST must always fire here:
    high complexity + low log density = unobservable. This documents
    that the AST decision is rooted in structure, not line count.
    """
    br = _load("too_few_logs_complex.smartrule")
    assert _ast_lines(br, "SR091") == {1}
