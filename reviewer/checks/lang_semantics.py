"""Language-semantics checks (SR055..SR059).

These checks exercise patterns specific to the BizRule scripting
language: alias mutations on arrays, ``:=``/``?=`` confusion, case
typos, unintended record auto-create, and unused variables.
"""
from __future__ import annotations

from ..ast.nodes import (
    AssignStmt,
    BinaryOp,
    Call,
    FieldAccess,
    ForCounter,
    ForeachList,
    ForeachTable,
    Identifier,
    Node,
    Script,
    TableSelector,
)
from ..engine.registry import register_check
from ..engine.visitor import Check


# ── SR059 UnusedVariableCheck ──────────────────────────────────────


@register_check(
    rule_id="SR059",
    category="lang",
    severity="info",
    description="Variable assigned but never read",
)
class UnusedVariableCheck(Check):
    """Flag any variable assigned (``x := ...`` or ``x ?= ...``) but
    never read elsewhere in the script.

    Implements SPEC §6 SR059. Catches dead-code residue from refactors,
    leftover debug variables, and typo-on-read-side mistakes
    (``total := compute(); ... return totl;`` — ``total`` looks unused
    because the read site misspelled it).

    Policy:
    - Only **bare-Identifier** assignment targets count. ``obj.F := v``,
      ``obj.F[cond] := v`` and ``arr[i] := v`` mutate external state,
      not a local variable.
    - **Counter-for** (``for X := 1 to 10 do { ... }``) and **foreach**
      loop variables are loop-introduced and are excluded from both
      the assignment set and the read set — flagging them as "unused"
      when the body genuinely doesn't reference them is too noisy for
      this codebase.
    - **Function and method names in callee position are not reads.**
    - Multiple assignments to the same name collapse onto the first
      assignment's line in the finding.
    - Severity is ``info``: the rule produces hints, not blocks.
    """

    def visit_Script(self, node: Script) -> None:
        assignments: dict[str, int] = {}
        reads: set[str] = set()
        for stmt in node.statements:
            _collect(stmt, assignments, reads)

        for name in sorted(assignments):
            if name in reads:
                continue
            self.ctx.emit(
                line=assignments[name],
                message=f"variable '{name}' assigned but never read",
            )


# ── SR059 helpers ──────────────────────────────────────────────────


# Comparison operators whose LHS, inside a TableSelector.condition,
# is a column name in the data model rather than a local variable.
_COMPARISON_OPS: frozenset[str] = frozenset(
    {"=", "!=", "<", ">", "<=", ">="}
)


def _collect(
    node: Node,
    assignments: dict[str, int],
    reads: set[str],
    in_selector_cond: bool = False,
) -> None:
    """Walk ``node`` populating the assignment table and the read set.

    The walk is hand-rolled rather than using ``children()`` so we can
    classify each context: assignment targets are *not* reads,
    loop-control variables are *neither* assignments nor reads, and
    callee identifiers are not reads.

    ``in_selector_cond`` is set when descending into a
    ``TableSelector.condition`` subtree. There, the LHS of a
    comparison-style ``BinaryOp`` (and bare ``Identifier`` leaves
    generally) is a column name from the data model, not a local
    variable, and is excluded from the read set. The RHS is collected
    normally — it can be a real variable.
    """
    if isinstance(node, AssignStmt):
        target = node.target
        if isinstance(target, Identifier):
            assignments.setdefault(target.name, node.line)
        else:
            # obj.F := v / arr[i] := v / obj.F[cond] := v — the target
            # itself contains reads (e.g. ``obj`` is read to locate
            # the field). Walk it.
            _collect(target, assignments, reads)
        _collect(node.value, assignments, reads)
        return

    if isinstance(node, ForCounter):
        # ``for X := start to end do body`` — X is loop-introduced.
        # start / end / body are normal subtrees and may contain reads.
        _collect(node.start, assignments, reads)
        _collect(node.end, assignments, reads)
        _collect(node.body, assignments, reads)
        return

    if isinstance(node, ForeachList):
        # ``foreach X in iterable do body`` — X is loop-introduced.
        _collect(node.iterable, assignments, reads)
        _collect(node.body, assignments, reads)
        return

    if isinstance(node, ForeachTable):
        # ``foreach obj.TABLE do body`` — no introduced variable, but
        # ``obj.TABLE`` is itself a read of ``obj``.
        _collect(node.target, assignments, reads)
        _collect(node.body, assignments, reads)
        return

    if isinstance(node, TableSelector):
        # ``obj.FIELD[condition]``: receiver chain is normal; the
        # condition subtree is column-context.
        _collect(node.target, assignments, reads)
        _collect(node.condition, assignments, reads, in_selector_cond=True)
        return

    if isinstance(node, Call):
        callee = node.callee
        if isinstance(callee, FieldAccess):
            # Method call ``obj.method(args)`` — the receiver chain is
            # read, the method name itself is not a variable.
            _collect(callee.target, assignments, reads)
        # Bare-Identifier callee (``getStatus()``): skip — function
        # names are not variables in scope.
        for arg in node.args:
            _collect(arg, assignments, reads)
        return

    if in_selector_cond and isinstance(node, BinaryOp):
        if node.op in _COMPARISON_OPS:
            # LHS is a column name; do not collect bare Identifiers
            # there. Walk a non-trivial LHS (e.g. ``obj.FIELD``)
            # without the flag so its receiver is still seen as a
            # real read.
            if not isinstance(node.left, Identifier):
                _collect(node.left, assignments, reads)
            # RHS may reference a real variable.
            _collect(node.right, assignments, reads)
            return
        # ``and`` / ``or`` (or any non-comparison): keep the column
        # context active and let the recursion handle each sub-clause.
        _collect(node.left, assignments, reads, in_selector_cond=True)
        _collect(node.right, assignments, reads, in_selector_cond=True)
        return

    if isinstance(node, Identifier):
        if in_selector_cond:
            # Bare column-name leaf inside a selector condition.
            return
        reads.add(node.name)
        return

    # Default: descend into all children, propagating the column-
    # context flag.
    for child in node.children():
        _collect(child, assignments, reads, in_selector_cond=in_selector_cond)


# ── SR057 CaseTypoVariableCheck ────────────────────────────────────


@register_check(
    rule_id="SR057",
    category="lang",
    severity="info",
    description=(
        "Identifiers in the same rule differ only in case "
        "(likely typo since names are case-sensitive)"
    ),
)
class CaseTypoVariableCheck(Check):
    """Flag identifier collisions that differ only in case.

    Implements SPEC §6 SR057. The scripting language is case-sensitive,
    so ``contrib`` and ``Contrib`` are two distinct variables. When
    both spellings appear in the same rule, almost always one is a
    typo: the assignment lands on the intended name, the read lands
    on a phantom, and the bug is silent at runtime.

    Detection is whole-script. Two passes, structurally:

    1. **variables**: bare-Identifier assignment targets only. Field
       and indexed assignments mutate external state; counter-for and
       foreach variables are loop-introduced. Same exclusions as
       SR059.
    2. **occurrences**: every ``Identifier`` node anywhere in the
       script (assignment targets, reads, arguments, conditions,
       receiver chains, indexed-access bases). Function-name
       identifiers in ``Call.callee`` position are excluded; field
       and method names live in ``FieldAccess.field`` (a ``str``,
       not an ``Identifier``) and are excluded by construction.

    A finding fires when, for some lowercase key:
    - the case-preserving spellings under that key number more than
      one, **and**
    - at least one of those spellings is a real assigned variable in
      this rule.

    The "at least one is a variable" gate is the false-positive
    filter: when *neither* spelling is assigned in the rule, both are
    almost certainly external constants / enums / functions, not
    something we can reason about.

    Severity is ``info``: hint, not block.
    """

    def visit_Script(self, node: Script) -> None:
        variables: set[str] = set()
        # name → first line on which that exact spelling appears.
        occurrences: dict[str, int] = {}
        for stmt in node.statements:
            _collect_case(stmt, variables, occurrences)

        # Group case-preserving spellings by their lowercase key.
        groups: dict[str, list[str]] = {}
        for name in occurrences:
            groups.setdefault(name.lower(), []).append(name)

        for key in sorted(groups):
            spellings = groups[key]
            if len(spellings) < 2:
                continue
            if not any(s in variables for s in spellings):
                continue
            # Stable, human-readable spelling list.
            spellings_sorted = sorted(spellings)
            first_line = min(occurrences[s] for s in spellings)
            joined = ", ".join(f"'{s}'" for s in spellings_sorted)
            self.ctx.emit(
                line=first_line,
                message=(
                    f"Possible case-typo: identifiers {joined} differ "
                    "only in case. At least one is an assigned "
                    "variable in this rule; the language is "
                    "case-sensitive, so these are distinct — likely "
                    "one is a typo."
                ),
            )


# ── SR057 helpers ──────────────────────────────────────────────────


def _collect_case(
    node: Node,
    variables: set[str],
    occurrences: dict[str, int],
    in_selector_cond: bool = False,
) -> None:
    """Walk ``node`` populating the assigned-variable set and the
    first-occurrence map (keyed by case-preserving identifier name).

    Mirrors ``_collect``'s context-classification rules so SR057 sees
    the same notion of "variable" as SR059, and additionally records
    every ``Identifier`` occurrence (including assignment targets).

    ``in_selector_cond`` mirrors the SR059 walker: inside a
    ``TableSelector.condition``, the LHS of a comparison and bare
    ``Identifier`` leaves are column names from the data model, not
    local variables, and are excluded from occurrences. The RHS of a
    comparison is collected normally — it may reference a real var.
    """
    if isinstance(node, AssignStmt):
        target = node.target
        if isinstance(target, Identifier):
            variables.add(target.name)
            occurrences.setdefault(target.name, target.line)
        else:
            _collect_case(target, variables, occurrences)
        _collect_case(node.value, variables, occurrences)
        return

    if isinstance(node, ForCounter):
        # X is loop-introduced; not a variable, not an occurrence.
        _collect_case(node.start, variables, occurrences)
        _collect_case(node.end, variables, occurrences)
        _collect_case(node.body, variables, occurrences)
        return

    if isinstance(node, ForeachList):
        _collect_case(node.iterable, variables, occurrences)
        _collect_case(node.body, variables, occurrences)
        return

    if isinstance(node, ForeachTable):
        _collect_case(node.target, variables, occurrences)
        _collect_case(node.body, variables, occurrences)
        return

    if isinstance(node, TableSelector):
        # Receiver chain is normal; the condition subtree is column
        # context.
        _collect_case(node.target, variables, occurrences)
        _collect_case(
            node.condition, variables, occurrences, in_selector_cond=True
        )
        return

    if isinstance(node, Call):
        callee = node.callee
        if isinstance(callee, FieldAccess):
            # Receiver chain is normal; method name is a string field.
            _collect_case(callee.target, variables, occurrences)
        # Bare-Identifier callee: excluded — function name, not a var.
        for arg in node.args:
            _collect_case(arg, variables, occurrences)
        return

    if in_selector_cond and isinstance(node, BinaryOp):
        if node.op in _COMPARISON_OPS:
            # LHS column name; skip bare Identifiers, but still walk
            # non-trivial LHS (e.g. ``obj.FIELD``) so its receiver
            # is counted as a real occurrence.
            if not isinstance(node.left, Identifier):
                _collect_case(node.left, variables, occurrences)
            _collect_case(node.right, variables, occurrences)
            return
        # ``and`` / ``or``: keep column context active.
        _collect_case(
            node.left, variables, occurrences, in_selector_cond=True
        )
        _collect_case(
            node.right, variables, occurrences, in_selector_cond=True
        )
        return

    if isinstance(node, Identifier):
        if in_selector_cond:
            return
        occurrences.setdefault(node.name, node.line)
        return

    for child in node.children():
        _collect_case(
            child, variables, occurrences, in_selector_cond=in_selector_cond
        )

# SR058_MARKER

# ── SR058 AutoCreateAssignCheck ────────────────────────────────────


from ._guards import (  # noqa: E402
    EMPTINESS_CHECK,
    PRESENCE_CHECK,
    VALUE_ENGAGEMENT,
    classify_comparison,
    expr_repr,
)


@register_check(
    rule_id="SR058",
    category="lang",
    severity="warning",
    description=(
        "Assignment to a TableSelector without an enclosing existence "
        "check — kernel may silently auto-create a record"
    ),
)
class AutoCreateAssignCheck(Check):
    """Flag ``obj.FIELD[COND] := v`` that is not guarded by a prior
    existence check on the same selector.

    Implements SPEC §6 SR058. The kernel's auto-create behaviour means
    that writing to a ``TableSelector`` whose row doesn't exist will
    *create* a new row to receive the write — almost always not what
    the developer intended. The conventional defence is an enclosing
    ``if (obj.F[C] != null) { ... }`` (or ``!= ""``, or bare truthy),
    or ``if (obj.F[C] = null) { ... } else { obj.F[C] := v }`` for
    the inverse shape.

    Decision procedure for each ``AssignStmt`` whose target is a
    ``TableSelector`` ``ts``:

    1. Walk ``ctx.if_stack`` from innermost outward.
    2. For each enclosing ``IfFrame``, classify how its condition
       references ``ts`` (see ``classify_comparison`` in
       ``_guards.py``):

       - ``EMPTINESS_CHECK`` (``ts = null``, ``ts = ""``, ``! ts``):
         the then-branch is the missing-row case → **fire** if we're
         in then; the else-branch is the present-row case → **safe**.
       - ``PRESENCE_CHECK`` (``ts != null``, ``ts != ""``, bare ``ts``):
         then = present-row → **safe**; else = missing-row → **fire**.
       - ``VALUE_ENGAGEMENT`` (any other comparison referencing ``ts``):
         the developer reads the value, implicitly asserting it
         exists — **safe in either branch**.
       - ``None`` (``ts`` not referenced at all): the frame is
         irrelevant; keep walking outward.

    3. The first frame that references ``ts`` decides the outcome —
       innermost guards take precedence over outer ones.
    4. If no enclosing frame references ``ts``, **fire** (no guard,
       no engagement).

    The check uses structural equality on ``TableSelector`` nodes
    (target, field, and condition recursively), so a guard on a
    *different* selector (``obj.G[C2]``) does not silence an
    assignment to ``obj.F[C]``.
    """

    def visit_AssignStmt(self, node: AssignStmt) -> None:
        target = node.target
        if not isinstance(target, TableSelector):
            return
        # Innermost-outward walk; first frame that references the
        # target settles the verdict.
        for frame in reversed(self.ctx.if_stack):
            cls = classify_comparison(frame.cond, target)
            if cls is None:
                continue
            if cls == VALUE_ENGAGEMENT:
                return  # safe in either branch
            if cls == EMPTINESS_CHECK:
                if frame.branch == "then":
                    self._fire(node, target)
                return
            if cls == PRESENCE_CHECK:
                if frame.branch == "else":
                    self._fire(node, target)
                return
            return  # defensive: unknown classification
        # No enclosing frame references this selector at all.
        self._fire(node, target)

    def _fire(self, node: AssignStmt, ts: TableSelector) -> None:
        src = expr_repr(ts)
        self.ctx.emit(
            line=node.line,
            message=(
                f"Assignment to TableSelector '{src}' at line "
                f"{node.line} is not guarded by an existence check. "
                "If no record matches the selector condition, the "
                "kernel silently creates a new record. Add an "
                "existence check (`if (TS != null)`, `if (TS != \"\")`,"
                " `if (TS)`, or any comparison that engages the value)"
                " before assigning."
            ),
        )
