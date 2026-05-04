"""Tests for reviewer.engine.runner and CheckContext (Phase 4)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from reviewer.ast.nodes import (
    AssignStmt,
    Block,
    ForeachList,
    Identifier,
    NumberLit,
    TryStmt,
)
from reviewer.engine import registry
from reviewer.engine.finding import Finding, Report
from reviewer.engine.registry import CHECKS, register_check
from reviewer.engine.runner import run_review
from reviewer.engine.visitor import Check, CheckContext


# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class FakeBizRule:
    """Minimal stand-in for parser.BizRule used by the engine."""

    name: str
    script: str
    comment: str = ""
    scope: str = ""


@pytest.fixture
def isolated_checks(monkeypatch):
    """Replace the global CHECKS list with an empty one for the test."""
    monkeypatch.setattr(registry, "CHECKS", [])
    # The runner imports CHECKS by name, re-bind it there too.
    from reviewer.engine import runner as runner_mod
    monkeypatch.setattr(runner_mod, "CHECKS", registry.CHECKS)
    return registry.CHECKS


# ── Clean-script path ───────────────────────────────────────────────


def test_run_review_on_clean_script_no_findings(isolated_checks) -> None:
    br = FakeBizRule(name="R1", script="x := 1;")
    report = run_review(br)
    assert isinstance(report, Report)
    assert report.rule_name == "R1"
    assert report.findings == ()


# ── Tokenize / parse error → SR999 ─────────────────────────────────


def test_tokenize_error_yields_single_sr999(isolated_checks) -> None:
    # Unterminated string at line 1.
    br = FakeBizRule(name="R2", script='x := "oops')
    report = run_review(br)
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.rule_id == "SR999"
    assert f.category == "lang"
    assert f.severity == "error"
    assert f.line == 1
    assert f.bizrule == "R2"


def test_parse_error_yields_single_sr999(isolated_checks) -> None:
    # Two statements on the same line without a separating ';' → ParseError.
    br = FakeBizRule(name="R3", script="x := 1 y := 2")
    report = run_review(br)
    assert len(report.findings) == 1
    assert report.findings[0].rule_id == "SR999"
    assert report.findings[0].line == 1


# ── Crashing check → SR998, others still run ───────────────────────


def test_crashing_check_yields_sr998_and_does_not_block_others(
    isolated_checks,
) -> None:
    @register_check(
        rule_id="SR_CRASH",
        category="logic",
        severity="error",
        description="boom",
    )
    class BoomCheck(Check):
        def visit_NumberLit(self, node) -> None:
            raise RuntimeError("kaboom")

    @register_check(
        rule_id="SR_OK",
        category="logic",
        severity="info",
        description="counts numbers",
    )
    class OkCheck(Check):
        def visit_NumberLit(self, node) -> None:
            self.ctx.emit(line=node.line, message=f"saw {node.value}")

    br = FakeBizRule(name="R4", script="x := 1;")
    report = run_review(br)
    rule_ids = [f.rule_id for f in report.findings]
    assert "SR998" in rule_ids
    assert "SR_OK" in rule_ids
    crash = next(f for f in report.findings if f.rule_id == "SR998")
    assert "BoomCheck" in crash.message
    assert "kaboom" in crash.message
    assert crash.bizrule == "R4"


# ── Loop / try stack balance ───────────────────────────────────────


def test_loop_and_try_stacks_balanced(isolated_checks) -> None:
    """A check observes loop/try depth; on exit, both stacks are empty."""
    observed: list[tuple[str, bool, bool]] = []

    @register_check(
        rule_id="SR_OBS",
        category="logic",
        severity="info",
        description="record stack state at every Identifier",
    )
    class ObsCheck(Check):
        def visit_Identifier(self, node) -> None:
            observed.append((node.name, self.ctx.in_loop(), self.ctx.in_try()))

    src = (
        "foreach item in items do {\n"
        "    try { x := item; } onerror { y := 0; }\n"
        "}\n"
    )
    br = FakeBizRule(name="R5", script=src)
    report = run_review(br)
    # No SR998 should appear (the obs check is well-behaved).
    assert all(f.rule_id != "SR998" for f in report.findings)

    # Every observation made *inside* the loop must report in_loop=True.
    inside = [o for o in observed if o[0] in {"item", "x", "y"}]
    assert inside, "expected some identifiers inside the loop"
    assert all(in_loop for (_, in_loop, _) in inside)

    # `x := item` is in the try-block; the onerror block is also part of the
    # TryStmt subtree, so `y` is observed under in_try=True as well.
    by_name = {name: (in_loop, in_try) for (name, in_loop, in_try) in observed}
    assert by_name["x"] == (True, True)
    assert by_name["y"] == (True, True)

    # After the walk completes the runner must have popped everything.
    # A second run_review call would hit a fresh CheckContext anyway, but
    # we assert via a fresh observation pass that depth resets between rules.
    observed.clear()
    br2 = FakeBizRule(name="R6", script="z := 1;")
    run_review(br2)
    assert observed == [("z", False, False)]
