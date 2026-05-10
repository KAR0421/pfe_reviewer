"""Tests for log checks (SR090 VerboseLogInLoopCheck,
SR091 TooFewLogsCheck).

SR091 talks about log density relative to *complexity* (branches,
loops, risky calls) rather than physical line count — see SPEC
footnote ``[^sr091]`` for the exact threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from reviewer import checks as _checks  # noqa: F401  (registers checks)
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


def _ast_lines(br: FakeBizRule, rule_id: str) -> set[int]:
    return {
        f.line for f in run_review(br).findings if f.rule_id == rule_id
    }


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
    """``foreach`` inside a comment line and ``msginfo`` inside a string
    literal must not fire: the tokenizer drops comments and tokenizes
    strings as opaque tokens.
    """
    br = _load("verbose_log_in_string_or_comment.smartrule")
    assert _ast_lines(br, "SR090") == set()


# ── Multi-log loops and post-loop logs ─────────────────────────────


def test_sr090_reports_every_log_call_in_loop() -> None:
    """Three log calls in the same loop body must each fire — one per
    call site, not once per loop — because the runner queries the loop
    stack on every visit.
    """
    br = _load("verbose_log_in_loop_multiple.smartrule")
    assert _ast_lines(br, "SR090") == {5, 6, 7}


def test_sr090_does_not_flag_logs_after_loop_closes() -> None:
    """A log after the loop's closing brace is not in the loop — the
    loop stack pops correctly when the body's ``Block`` ends.
    """
    br = _load("verbose_log_after_loop_closes.smartrule")
    assert _ast_lines(br, "SR090") == set()


# ════════════════════════════════════════════════════════════════════
# SR091 TooFewLogsCheck
# ════════════════════════════════════════════════════════════════════
#
# Fires when stmts > 50 AND log_calls * 5 < complexity, where
# complexity = branches + loops + risky calls.


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
