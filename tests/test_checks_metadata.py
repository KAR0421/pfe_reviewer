"""Tests for BizRule-level metadata checks (SR011, SR060, SR061,
SR062 — module ``reviewer/checks/metadata.py``).

These checks override ``visit_BizRule`` rather than walking the
script AST. They emit findings with ``line=0`` because the offending
location is the rule's metadata block, not any specific script line.
Synthetic fixtures are built directly from the ``parser.BizRule``
dataclass so the tests don't depend on any XML round-trip.
"""
from __future__ import annotations

from pathlib import Path

# Importing the module triggers @register_check for the metadata checks.
from reviewer.checks import metadata  # noqa: F401
from reviewer.engine.runner import run_review

from parser import BizRule, Trigger, extract_bizrules


REPO_ROOT = Path(__file__).parent.parent


def _make(
    *,
    name: str = "DUMMY",
    script: str = "",
    display_names: dict[int, str] | None = None,
    triggers: tuple[Trigger, ...] = (),
) -> BizRule:
    return BizRule(
        name=name,
        comment="",
        scope="",
        script=script,
        display_names=display_names,
        triggers=triggers,
    )


def _findings(br: BizRule, rule_id: str, **kwargs):
    report = run_review(br, **kwargs)
    return [f for f in report.findings if f.rule_id == rule_id]


# ════════════════════════════════════════════════════════════════════
# SR011 — MissingDisplayNameCheck
# ════════════════════════════════════════════════════════════════════

def test_sr011_no_display_names_fires() -> None:
    br = _make(display_names=None)
    findings = _findings(br, "SR011")
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 0
    assert f.severity == "warning"
    assert f.category == "docs"
    assert "Missing SMARTRULE_NAME" in f.message


def test_sr011_one_display_name_silent() -> None:
    """A name in a single language is enough to satisfy the rule."""
    br = _make(display_names={0: "Some name"})
    assert _findings(br, "SR011") == []


def test_sr011_real_pack_update_document_process_silent() -> None:
    """Production fixture has display names in two languages."""
    brs = extract_bizrules(str(REPO_ROOT / "sample.pack"))
    target = next(b for b in brs if b.name == "UPDATE_DOCUMENT_PROCESS")
    assert _findings(target, "SR011", pack_bizrules=brs) == []


# ════════════════════════════════════════════════════════════════════
# SR060 — MalformedTriggerCheck (object-required types only)
# ════════════════════════════════════════════════════════════════════

def test_sr060_no_triggers_fires_with_missing_message() -> None:
    br = _make(display_names={0: "x"}, triggers=())
    findings = _findings(br, "SR060")
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 0
    assert f.severity == "warning"
    assert f.category == "scope"
    assert "Missing SMARTRULE_TRIGGER" in f.message


def test_sr060_object_not_required_type_with_empty_object_silent() -> None:
    """Type 13 ("operation") doesn't require a TRIGGER_OBJECT — empty
    is valid. The pre-correction check fired here and produced a
    false positive on real production data; this test pins that
    regression closed.
    """
    br = _make(
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=13, trigger_object=""),),
    )
    assert _findings(br, "SR060") == []


def test_sr060_required_type_with_empty_object_fires() -> None:
    """Type 40 ("field to be changed") requires a field name."""
    br = _make(
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=40, trigger_object=""),),
    )
    findings = _findings(br, "SR060")
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 0
    assert f.severity == "warning"
    assert f.category == "scope"
    assert "Missing TRIGGER_OBJECT" in f.message
    assert "trigger #1" in f.message
    assert "TRIGGER_TYPE=40" in f.message
    assert "field to be changed" in f.message


def test_sr060_required_type_with_object_silent() -> None:
    br = _make(
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=40, trigger_object="someField"),),
    )
    assert _findings(br, "SR060") == []


def test_sr060_type_60_is_sr061_territory_silent() -> None:
    """Type 60 has different semantics (RULE_CODE, not field). SR060
    leaves it to SR061 to avoid double-flagging.
    """
    br = _make(
        name="A",
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=60, trigger_object=""),),
    )
    assert _findings(br, "SR060") == []


def test_sr060_real_pack_update_document_process_silent() -> None:
    """Real regression: ``UPDATE_DOCUMENT_PROCESS`` uses
    ``TRIGGER_TYPE=13`` with an empty ``TRIGGER_OBJECT``. Type 13
    doesn't require an object, so SR060 must stay silent.
    """
    brs = extract_bizrules(str(REPO_ROOT / "sample.pack"))
    target = next(b for b in brs if b.name == "UPDATE_DOCUMENT_PROCESS")
    assert _findings(target, "SR060", pack_bizrules=brs) == []


def test_sr060_real_pack2_well_formed_silent() -> None:
    brs = extract_bizrules(str(REPO_ROOT / "sample2.pack"))
    for target in brs:
        assert _findings(target, "SR060", pack_bizrules=brs) == []


# ════════════════════════════════════════════════════════════════════
# SR061 — Type-60 self-reference invariant
# ════════════════════════════════════════════════════════════════════

def test_sr061_self_referencing_type60_silent() -> None:
    """A single type-60 trigger with TRIGGER_OBJECT == RULE_CODE
    satisfies the self-reference invariant.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=60, trigger_object="MY_RULE"),),
    )
    assert _findings(br, "SR061", pack_bizrules=[br]) == []


def test_sr061_no_type60_trigger_silent() -> None:
    """SR061 only cares about type-60 triggers. A rule with only
    other types must produce no SR061 findings.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=13, trigger_object="anything"),),
    )
    assert _findings(br, "SR061", pack_bizrules=[br]) == []


def test_sr061_type60_no_self_reference_fires_self_only() -> None:
    """A type-60 trigger whose TRIGGER_OBJECT is not the rule's own
    RULE_CODE → fires the self-reference invariant finding.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=60, trigger_object="OTHER"),),
    )
    findings = _findings(br, "SR061")
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 0
    assert f.severity == "warning"
    assert f.category == "scope"
    assert "must include at least one trigger" in f.message
    assert "'MY_RULE'" in f.message


def test_sr061_two_type60_triggers_one_self_references_silent() -> None:
    """Self-reference invariant only requires *at least one* type-60
    trigger to point at the rule's own RULE_CODE — extras pointing
    elsewhere are fine, regardless of where they point.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(
            Trigger(trigger_type=60, trigger_object="OTHER"),
            Trigger(trigger_type=60, trigger_object="MY_RULE"),
        ),
    )
    assert _findings(br, "SR061") == []


def test_sr061_two_type60_triggers_neither_self_references_one_self_finding() -> None:
    """No matter how many type-60 triggers fail self-reference, the
    invariant fires *once* per rule.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(
            Trigger(trigger_type=60, trigger_object="A"),
            Trigger(trigger_type=60, trigger_object="B"),
        ),
    )
    findings = _findings(br, "SR061")
    assert len(findings) == 1
    assert findings[0].category == "scope"


def test_sr061_type60_with_external_reference_silent() -> None:
    """Chaining to a RULE_CODE outside the pack is a legitimate
    pattern. As long as one type-60 trigger self-references, SR061
    must stay silent on the external reference.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(
            Trigger(trigger_type=60, trigger_object="SOME_EXTERNAL_RULE"),
            Trigger(trigger_type=60, trigger_object="MY_RULE"),
        ),
    )
    # pack_bizrules contains only MY_RULE; SOME_EXTERNAL_RULE is
    # deliberately absent — must NOT fire.
    assert _findings(br, "SR061", pack_bizrules=[br]) == []


def test_sr061_self_reference_works_in_single_rule_mode() -> None:
    """Single-rule review mode (no pack context): a self-referencing
    type-60 trigger is silent.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=60, trigger_object="MY_RULE"),),
    )
    assert _findings(br, "SR061") == []


def test_sr061_empty_pack_bizrules_self_ref_still_applies() -> None:
    """Single-rule mode but the trigger doesn't self-reference:
    the self-reference invariant still fires.
    """
    br = _make(
        name="MY_RULE",
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=60, trigger_object="OTHER"),),
    )
    findings = _findings(br, "SR061")
    assert len(findings) == 1
    assert findings[0].category == "scope"


def test_sr061_real_pack_silent() -> None:
    """Pack 1: rule has only a type-13 trigger, no type-60 → SR061
    has nothing to say.
    """
    brs = extract_bizrules(str(REPO_ROOT / "sample.pack"))
    for target in brs:
        assert _findings(target, "SR061", pack_bizrules=brs) == []


def test_sr061_real_pack2_intra_resolution_silent() -> None:
    """Pack 2: every BizRule has a type-60 trigger self-referencing
    its own RULE_CODE → invariant satisfied.
    """
    brs = extract_bizrules(str(REPO_ROOT / "sample2.pack"))
    for target in brs:
        assert _findings(target, "SR061", pack_bizrules=brs) == []


# ════════════════════════════════════════════════════════════════════
# SR062 — InvalidTriggerTypeCheck
# ════════════════════════════════════════════════════════════════════

def test_sr062_invalid_type_fires() -> None:
    br = _make(
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=99, trigger_object="X"),),
    )
    findings = _findings(br, "SR062")
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 0
    assert f.severity == "info"
    assert f.category == "scope"
    assert "TRIGGER_TYPE 99" in f.message


def test_sr062_valid_type_silent() -> None:
    br = _make(
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=13, trigger_object="X"),),
    )
    assert _findings(br, "SR062") == []


def test_sr062_none_type_skipped() -> None:
    """``trigger_type is None`` is SR060's malformed case — SR062
    intentionally stays silent so reviewers don't see two findings
    for the same root cause.
    """
    br = _make(
        display_names={0: "x"},
        triggers=(Trigger(trigger_type=None, trigger_object="X"),),
    )
    assert _findings(br, "SR062") == []


def test_sr062_real_pack_silent() -> None:
    """Both packs use TRIGGER_TYPE values inside the schema enum
    (13 and 60); SR062 must stay silent on production data.
    """
    for pack in ("sample.pack", "sample2.pack"):
        brs = extract_bizrules(str(REPO_ROOT / pack))
        for target in brs:
            assert _findings(target, "SR062", pack_bizrules=brs) == []


# ════════════════════════════════════════════════════════════════════
# SR002 — RuleCodeNamingCheck
# ════════════════════════════════════════════════════════════════════


# ── Positive (fires) ──────────────────────────────────────────────


def test_sr002_lowercase_letters_fires() -> None:
    br = _make(name="myRule")
    findings = _findings(br, "SR002")
    assert len(findings) == 1
    f = findings[0]
    assert f.line == 0
    assert f.severity == "warning"
    assert f.category == "naming"
    assert "'myRule'" in f.message
    assert "naming convention" in f.message


def test_sr002_leading_digit_fires() -> None:
    br = _make(name="1_RULE")
    findings = _findings(br, "SR002")
    assert len(findings) == 1
    assert "'1_RULE'" in findings[0].message


def test_sr002_hyphen_fires() -> None:
    br = _make(name="RULE-X")
    findings = _findings(br, "SR002")
    assert len(findings) == 1
    assert "'RULE-X'" in findings[0].message


def test_sr002_too_short_fires() -> None:
    """Two characters fails the ``{2,}`` quantifier on the trailing run."""
    br = _make(name="RU")
    findings = _findings(br, "SR002")
    assert len(findings) == 1
    assert "'RU'" in findings[0].message


def test_sr002_space_fires() -> None:
    br = _make(name="RULE NAME")
    findings = _findings(br, "SR002")
    assert len(findings) == 1
    assert "'RULE NAME'" in findings[0].message


# ── Negative (silent) ─────────────────────────────────────────────


def test_sr002_canonical_uppercase_silent() -> None:
    br = _make(name="UPDATE_DOCUMENT_PROCESS")
    assert _findings(br, "SR002") == []


def test_sr002_with_digits_silent() -> None:
    br = _make(name="TRANSCO_NPC23")
    assert _findings(br, "SR002") == []


def test_sr002_minimum_length_silent() -> None:
    """Three uppercase letters is the smallest acceptable code."""
    br = _make(name="RULE")
    assert _findings(br, "SR002") == []


# ── Real-pack regression ──────────────────────────────────────────


def test_sr002_real_pack_silent() -> None:
    """Both production packs use compliant RULE_CODEs
    (``UPDATE_DOCUMENT_PROCESS`` in sample.pack,
    ``COMPUTE_TEMPLATE_ORDER`` and ``COMPUTE_START_WORKFLOW`` in
    sample2.pack). SR002 must stay silent on real data.
    """
    for pack in ("sample.pack", "sample2.pack"):
        brs = extract_bizrules(str(REPO_ROOT / pack))
        for target in brs:
            assert _findings(target, "SR002", pack_bizrules=brs) == []
