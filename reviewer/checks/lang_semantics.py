"""Language-semantics checks (SR055..SR059).

These checks exercise patterns specific to the BizRule scripting
language: alias mutations on arrays, ``:=``/``?=`` confusion, case
typos, unintended record auto-create, and unused variables.
"""
from __future__ import annotations

from ..ast.nodes import (
    ArrayIndex,
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


# SR055_MARKER

# ── SR055 ArrayAliasCheck ──────────────────────────────────────────


# Built-in callees whose return value is an array. A bare-Identifier
# assignment ``x := <call>`` where the callee name (case-sensitive)
# is in this set tags ``x`` as array-typed from that line forward.
# ``arraysize`` is *not* in this set: it returns the integer length,
# not an array, so ``n := arraysize(a)`` does not tag ``n``.
ARRAY_RETURNING_BUILTINS: frozenset[str] = frozenset({
    "array",
    "arraycopy",
    "arrayappend",
    "arrayremove",
    "arrayunion",
    "arraysubset",
    "arraysubfind",
    "arraysort",
})


@register_check(
    rule_id="SR055",
    category="lang",
    severity="warning",
    description=(
        "Array alias: ``b := a`` between array-typed variables with "
        "no subsequent ``arraycopy`` — mutations to ``b`` will "
        "affect ``a``"
    ),
)
class ArrayAliasCheck(Check):
    """Flag a plain array-to-array assignment ``b := a`` that is
    followed by a mutation of either side.

    Implements SPEC §6 SR055. In this language assigning one array
    variable to another aliases them — both names refer to the same
    underlying array, so any mutation through one is visible through
    the other. The intentional way to copy is ``b := arraycopy(a);``.

    Detection is whole-script in two passes over a single
    source-order event log:

    1. Walk the script, collecting events for every ``AssignStmt``
       whose target is a bare ``Identifier`` and for every indexed
       assignment ``b[i] := v`` (target is ``ArrayIndex`` whose
       ``array`` is a bare ``Identifier``). A bare-Identifier
       assignment whose RHS is a ``Call`` to one of
       ``ARRAY_RETURNING_BUILTINS`` (or a bare ``Identifier``
       already known to be array-typed) tags the LHS as array-typed
       from that point on. A bare-Identifier-to-bare-Identifier
       assignment whose RHS is array-typed and whose RHS is *not*
       wrapped in ``arraycopy(...)`` is recorded as a candidate
       alias ``(b, a, line)`` and ``b`` becomes array-typed too.

    2. After the walk, for each candidate ``(b, a, alias_line)``,
       scan the event log for a *mutation* of either ``b`` or ``a``
       at any source line strictly greater than ``alias_line``.
       A mutation is either a re-assignment (``b := …``) or an
       indexed write (``b[i] := …`` / ``a[i] := …``). If found,
       fire at ``alias_line``; otherwise stay silent (the alias may
       be deliberate — just a different name for the same array).

    Loop-introduced names (``for i := …`` and ``foreach x in …``)
    are excluded from candidate-alias targets/sources: loop
    variables aren't general variables, and using one as either
    side of an alias is rare enough that the false-positive cost
    isn't worth it.

    The ``arraycopy(...)`` call on the RHS is the documented
    correct pattern; it tags the LHS as array-typed but does not
    record an alias.
    """

    def visit_Script(self, node: Script) -> None:
        # Loop-introduced names — excluded from alias bookkeeping.
        loop_vars: set[str] = set()
        self._collect_loop_vars(node, loop_vars)

        # Source-order events. ``kind`` is one of:
        #   "assign_array_typed"  payload=name           (LHS now array-typed)
        #   "assign_other"        payload=name           (LHS no longer array-typed)
        #   "alias"               payload=(b, a)         (candidate alias)
        #   "index_write"         payload=name           (b[i] := …)
        events: list[tuple[str, object, int]] = []
        array_typed: set[str] = set()
        candidates: list[tuple[str, str, int]] = []  # (b, a, line)

        for stmt in self._iter_stmts(node):
            self._classify_stmt(stmt, array_typed, candidates, loop_vars, events)

        # Pass 2: for each candidate, look for a later mutation.
        for b, a, alias_line in candidates:
            mut_line = self._find_later_mutation(events, {b, a}, alias_line)
            if mut_line is None:
                continue
            self.ctx.emit(
                line=alias_line,
                message=(
                    f"Array alias at line {alias_line}: '{b} := {a}' "
                    "aliases both variables to the same array. A later "
                    f"mutation (line {mut_line}) will affect both. Use "
                    f"'arraycopy({a})' if an independent copy is intended."
                ),
            )

    # ── Helpers ──────────────────────────────────────────────────

    def _iter_stmts(self, node: Node):
        """Yield every node in source order (pre-order DFS).

        Statement classification looks at ``AssignStmt`` nodes
        wherever they appear (top-level or nested in branches/loops/
        try blocks). The walk visits children in the order
        ``Node.children()`` yields them.
        """
        yield node
        for child in node.children():
            yield from self._iter_stmts(child)

    def _collect_loop_vars(self, node: Node, into: set[str]) -> None:
        if isinstance(node, ForCounter):
            into.add(node.var.name)
        elif isinstance(node, ForeachList):
            into.add(node.var.name)
        for child in node.children():
            self._collect_loop_vars(child, into)

    def _classify_stmt(
        self,
        stmt: Node,
        array_typed: set[str],
        candidates: list[tuple[str, str, int]],
        loop_vars: set[str],
        events: list[tuple[str, object, int]],
    ) -> None:
        if not isinstance(stmt, AssignStmt):
            return
        target = stmt.target
        line = stmt.line

        # Indexed write: ``b[i] := v`` — mutation of ``b``.
        if isinstance(target, ArrayIndex) and isinstance(target.array, Identifier):
            events.append(("index_write", target.array.name, line))
            return

        # Anything other than a bare-Identifier target is out of scope:
        # field/TableSelector writes never participate in aliasing.
        if not isinstance(target, Identifier):
            return

        name = target.name
        value = stmt.value

        # Loop-introduced names: excluded from alias bookkeeping.
        if name in loop_vars:
            return

        # 1) RHS is an arraycopy(...) call — LHS becomes array-typed,
        #    but NOT an alias (this is the documented correct copy).
        if (
            isinstance(value, Call)
            and isinstance(value.callee, Identifier)
            and value.callee.name == "arraycopy"
        ):
            array_typed.add(name)
            events.append(("assign_array_typed", name, line))
            return

        # 2) RHS is any other array-returning built-in call → array-typed.
        if (
            isinstance(value, Call)
            and isinstance(value.callee, Identifier)
            and value.callee.name in ARRAY_RETURNING_BUILTINS
        ):
            array_typed.add(name)
            events.append(("assign_array_typed", name, line))
            return

        # 3) RHS is a bare Identifier referring to an array-typed var,
        #    excluding loop variables → alias candidate.
        if (
            isinstance(value, Identifier)
            and value.name in array_typed
            and value.name not in loop_vars
        ):
            candidates.append((name, value.name, line))
            array_typed.add(name)
            events.append(("alias", (name, value.name), line))
            return

        # 4) Anything else — LHS becomes non-array-typed. If it was
        #    previously tagged, drop the tag (re-assigning ``b := 5``
        #    after ``b := a`` ends ``b``'s array-typed status). The
        #    re-assignment itself counts as a mutation of ``b``.
        if name in array_typed:
            array_typed.discard(name)
        events.append(("assign_other", name, line))

    def _find_later_mutation(
        self,
        events: list[tuple[str, object, int]],
        names: set[str],
        after_line: int,
    ) -> int | None:
        """Return the first line strictly greater than ``after_line``
        on which any name in ``names`` is mutated, or ``None``.

        A mutation is either an ``"index_write"`` event or a
        re-assignment (``"assign_array_typed"`` or ``"assign_other"``).
        An ``"alias"`` event with the same target also counts as a
        re-assignment.
        """
        for kind, payload, line in events:
            if line <= after_line:
                continue
            if kind == "index_write" and payload in names:
                return line
            if kind in ("assign_array_typed", "assign_other") and payload in names:
                return line
            if kind == "alias":
                b, _a = payload  # type: ignore[misc]
                if b in names:
                    return line
        return None
