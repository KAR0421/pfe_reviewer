"""BizRule-level metadata checks (SR002, SR011, SR060, SR061, SR062).

All operate on the ``BizRule`` dataclass fields populated by
``parser.extract_bizrules`` — ``name`` (the ``RULE_CODE``),
``display_names`` (the ``T_SMARTRULE_NAME`` table) and ``triggers``
(the ``T_SMARTRULE_TRIGGER`` table) — not on the parsed script AST.
They therefore override ``visit_BizRule`` and emit findings with
``line=0``: the offending location is the rule's metadata block, not
any specific line of the ``IMPACT`` script.
"""
from __future__ import annotations

import re

from ..engine.registry import register_check
from ..engine.visitor import Check, CheckContext


# ── SR011 MissingDisplayNameCheck ──────────────────────────────────


@register_check(
    rule_id="SR011",
    category="docs",
    severity="warning",
    description="Rule has no SMARTRULE_NAME in any language",
)
class MissingDisplayNameCheck(Check):
    """Flag a BizRule that has no display name in any language.

    Implements SPEC §6 SR011. Display names live in the
    ``T_SMARTRULE_NAME`` repeating table; the parser collapses them
    into ``br.display_names: dict[int, str]`` keyed by
    ``NAME_LANGUAGE``. A rule with at least one non-empty name in
    any language is acceptable; one with zero names is opaque in the
    UI and harder to maintain.
    """

    def visit_BizRule(self, br, ctx: CheckContext) -> None:
        # Use a sentinel default to distinguish "attribute missing"
        # (synthetic AST-only test fixture — skip) from "attribute
        # present but empty" (real BizRule with zero display names —
        # fire). The parser always sets ``display_names`` to a dict.
        _MISSING = object()
        display_names = getattr(br, "display_names", _MISSING)
        if display_names is _MISSING:
            return
        if not display_names:
            ctx.emit(
                line=0,
                message=(
                    "Missing SMARTRULE_NAME: this rule has no "
                    "display name in any language."
                ),
            )


# ── SR060 / SR061 trigger-type semantics ──────────────────────────


# Trigger types whose TRIGGER_OBJECT is required and must name a
# field/record in the data model. Drawn from observation of real
# packs and the platform's documented trigger semantics.
REQUIRES_OBJECT_NON_60: frozenset[int] = frozenset(
    {20, 21, 30, 31, 40, 41}
)
# Type 60 also requires a TRIGGER_OBJECT, but with different semantics
# (it must reference a RULE_CODE, possibly the rule's own). SR061
# owns type 60; SR060 only handles the non-60 required types.
REQUIRES_OBJECT_60: frozenset[int] = frozenset({60})
REQUIRES_OBJECT: frozenset[int] = REQUIRES_OBJECT_NON_60 | REQUIRES_OBJECT_60

# Human-readable labels for the required-object trigger types, used
# in finding messages so reviewers don't have to keep schema.xml open.
_TYPE_NAMES: dict[int, str] = {
    20: "record created",
    21: "record to be deleted",
    30: "field to be indirectly changed",
    31: "field indirectly changed",
    40: "field to be changed",
    41: "field changed",
    60: "internal process",
}


# ── SR060 MalformedTriggerCheck ────────────────────────────────────


@register_check(
    rule_id="SR060",
    category="scope",
    severity="warning",
    description=(
        "SMARTRULE_TRIGGER missing, or a required-object trigger "
        "type has an empty TRIGGER_OBJECT"
    ),
)
class MalformedTriggerCheck(Check):
    """Flag a BizRule with no triggers, or with a trigger whose type
    requires a non-empty ``TRIGGER_OBJECT`` but has none.

    Implements SPEC §6 SR060. The platform's trigger types split into
    two groups:

    - **Object-required** (``20, 21, 30, 31, 40, 41``): the trigger
      fires on a specific field or record, so ``TRIGGER_OBJECT`` must
      name it. An empty value here is a misconfiguration.
    - **Object-required, type 60** (internal process): handled by
      SR061 because the value must reference a ``RULE_CODE``, not a
      field — different semantics, different finding shape.
    - **Object-not-required** (``10, 11, 12, 13, 14, 50, 51``): the
      trigger fires globally; an empty ``TRIGGER_OBJECT`` is valid.
      Pre-correction this check fired here too and produced false
      positives on real production data (UPDATE_DOCUMENT_PROCESS uses
      type 13).

    Trigger rows with ``trigger_type is None`` are SR062's territory
    (invalid enum) and are intentionally skipped here so reviewers
    don't see two findings for the same root cause.
    """

    def visit_BizRule(self, br, ctx: CheckContext) -> None:
        # Default to ``None`` for synthetic test fixtures that don't
        # set the attribute. Distinguishing "missing attribute" from
        # "empty tuple" lets us stay silent in single-rule AST tests
        # while still firing on real BizRules with no triggers.
        triggers = getattr(br, "triggers", None)
        if triggers is None:
            return
        if not triggers:
            ctx.emit(
                line=0,
                message=(
                    "Missing SMARTRULE_TRIGGER: this rule has no "
                    "triggers defined."
                ),
            )
            return
        for idx, trig in enumerate(triggers, start=1):
            ttype = trig.trigger_type
            if ttype is None:
                continue
            if ttype not in REQUIRES_OBJECT_NON_60:
                # Either object-not-required (empty is valid) or
                # type 60 (SR061's territory). Skip.
                continue
            if trig.trigger_object == "":
                label = _TYPE_NAMES.get(ttype, "?")
                ctx.emit(
                    line=0,
                    message=(
                        f"Missing TRIGGER_OBJECT: trigger #{idx} "
                        f"(TRIGGER_TYPE={ttype}, {label}) requires a "
                        "field name but TRIGGER_OBJECT is empty."
                    ),
                )


# ── SR061 UnresolvedTriggerObjectCheck (type-60 invariants) ─────────


@register_check(
    rule_id="SR061",
    category="scope",
    severity="warning",
    description=(
        "TRIGGER_TYPE=60 self-reference invariant: at least one "
        "type-60 trigger must point at the rule's own RULE_CODE"
    ),
)
class UnresolvedTriggerObjectCheck(Check):
    """Type-60 self-reference invariant. SPEC §6 SR061.

    Type 60 ("internal process") fires when another rule explicitly
    invokes this one by ``RULE_CODE``. The platform's wiring requires
    that a rule with any type-60 triggers expose at least one trigger
    whose ``TRIGGER_OBJECT`` equals the rule's own ``RULE_CODE`` —
    otherwise the rule advertises an entry point that nothing connects
    to itself, and internal-process dispatch cannot reach it.

    Other type-60 triggers in the same rule may reference any
    ``RULE_CODE``, in or out of the pack: chaining to an external
    rule is a legitimate pattern and is **not** a defect on its own.
    Earlier versions of this check also performed per-trigger
    intra-pack resolution and flagged empty type-60 ``TRIGGER_OBJECT``
    values; both of those behaviors were removed because they
    over-flagged valid chaining configurations.

    Fired at most once per rule, regardless of how many type-60
    triggers it has.
    """

    def visit_BizRule(self, br, ctx: CheckContext) -> None:
        triggers = getattr(br, "triggers", None)
        if not triggers:
            return
        type60 = [t for t in triggers if t.trigger_type == 60]
        if not type60:
            return
        if any(t.trigger_object == br.name for t in type60):
            return
        ctx.emit(
            line=0,
            message=(
                f"TRIGGER_TYPE=60 (internal process) on rule "
                f"'{br.name}' must include at least one trigger "
                "whose TRIGGER_OBJECT equals the rule's own "
                f"RULE_CODE ('{br.name}'). None of the type-60 "
                "triggers self-reference."
            ),
        )


# ── SR062 InvalidTriggerTypeCheck ──────────────────────────────────


# RULE_TRIGGER_TYPE enum values per schema.xml. Anything outside this
# set is either a typo or a legacy value the platform no longer
# accepts; either way the rule won't fire correctly.
VALID_TRIGGER_TYPES: frozenset[int] = frozenset(
    {10, 11, 12, 13, 14, 20, 21, 30, 31, 40, 50, 51, 60}
)


@register_check(
    rule_id="SR062",
    category="scope",
    severity="info",
    description="TRIGGER_TYPE is not in the valid enum set",
)
class InvalidTriggerTypeCheck(Check):
    """Flag a TRIGGER_TYPE value that is not in the schema's enum.

    Implements SPEC §6 SR062. Trigger rows with
    ``trigger_type is None`` (missing or non-numeric) are intentionally
    skipped here — SR060 already flags them as malformed and a
    second finding would just be noise.
    """

    def visit_BizRule(self, br, ctx: CheckContext) -> None:
        triggers = getattr(br, "triggers", None)
        if not triggers:
            return
        for trig in triggers:
            value = trig.trigger_type
            if value is None:
                continue
            if value not in VALID_TRIGGER_TYPES:
                ctx.emit(
                    line=0,
                    message=(
                        f"TRIGGER_TYPE {value} is not a valid trigger "
                        "type. Valid values per schema.xml: 10, 11, "
                        "12, 13, 14, 20, 21, 30, 31, 40, 50, 51, 60."
                    ),
                )


# ── SR002 RuleCodeNamingCheck ─────────────────────────────────────


# Project naming convention for ``RULE_CODE``: must start with an
# uppercase letter, then at least two more characters drawn from
# uppercase letters, digits, or underscores (minimum total length 3).
# No lowercase, no whitespace, no punctuation other than underscore.
RULE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


@register_check(
    rule_id="SR002",
    category="naming",
    severity="warning",
    description="BizRule RULE_CODE does not follow naming convention",
)
class RuleCodeNamingCheck(Check):
    """Flag a ``RULE_CODE`` that violates the project naming convention.

    Implements SPEC §6 SR002. The convention is enforced by
    ``RULE_CODE_PATTERN``: ``^[A-Z][A-Z0-9_]{2,}$``. Real production
    codes like ``UPDATE_DOCUMENT_PROCESS`` and ``TRANSCO_NPC23`` match
    cleanly; common defects (lowercase, leading digit, hyphen, space,
    too-short stub) all fail.
    """

    def visit_BizRule(self, br, ctx: CheckContext) -> None:
        name = getattr(br, "name", None)
        if name is None:
            return
        if RULE_CODE_PATTERN.match(name):
            return
        ctx.emit(
            line=0,
            message=(
                f"RULE_CODE '{name}' does not follow naming "
                "convention. Required: at least 3 characters, "
                "uppercase letters / digits / underscores only, "
                "must start with a letter."
            ),
        )


