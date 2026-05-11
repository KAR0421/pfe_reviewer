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
# ``sample.pack.xml`` / ``sample.pack2.xml``. Their SR059 findings are
# documented here so any future change that alters the read/assignment
# walker is caught by an obvious diff in expected output.


def test_sr059_real_pack_update_document_process() -> None:
    """``update_document_process.smartrule`` (sample.pack.xml).

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
    """``compute_template_order.smartrule`` (sample.pack2.xml).

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
