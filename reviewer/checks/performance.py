"""Performance checks (SR030..SR034)."""
from __future__ import annotations

from ..ast.nodes import (
    AssignStmt,
    Call,
    Expr,
    FieldAccess,
    ForCounter,
    Identifier,
    Node,
    NumberLit,
    Script,
    StringLit,
)
from ..engine.registry import register_check
from ..engine.visitor import Check
from ._sql import (
    Conjunct,
    ParsedQuery,
    collect_string_assignments,
    flatten_query_arg,
    parse_query,
)


@register_check(
    rule_id="SR030",
    category="performance",
    severity="error",
    description="SQL query executed inside a loop",
)
class SqlInLoopCheck(Check):
    """Flag ``getSqlData(...)`` calls executed inside any loop construct.

    Implements SPEC §8 SR030: SQL inside loops is the canonical
    repeated-query performance footgun; the kernel re-executes the query
    once per iteration.
    """

    def visit_Call(self, node: Call) -> None:
        if not self.ctx.in_loop():
            return
        callee = node.callee
        if isinstance(callee, Identifier) and callee.name.lower() == "getsqldata":
            outer = self.ctx.current_loop()
            self.ctx.emit(
                line=node.line,
                message=(
                    f"SQL query inside loop (outer loop at line {outer.line})"
                ),
            )


@register_check(
    rule_id="SR031",
    category="performance",
    severity="warning",
    description=(
        "Nested loops, severity graded by bound-ness and side-effects "
        "(info / warning / error)."
    ),
)
class NestedLoopCheck(Check):
    """Flag any loop that is itself nested inside another loop.

    Implements SPEC §8 SR031. Severity is graded:

    - **info**: both loops are provably bounded by literal counters
      (e.g. ``for i := 1 to 5``); cost is O(constant), informational
      only.
    - **error**: the inner loop body contains an expensive call
      (SQL access, service invocation, object lookup, or any method
      call) — quadratic cost on top of a per-iteration side effect is
      almost always a bug.
    - **warning**: every other case (default).

    The check uses the runner-maintained loop stack
    (``CheckContext._loop_stack``), so loop keywords inside comments
    or string literals, ``do { ... } while (...)`` shapes, and ``}``
    closing non-loop blocks all behave correctly by construction.
    """

    def visit_ForCStyle(self, node) -> None:
        self._maybe_emit(node)

    def visit_ForCounter(self, node) -> None:
        self._maybe_emit(node)

    def visit_ForeachList(self, node) -> None:
        self._maybe_emit(node)

    def visit_ForeachTable(self, node) -> None:
        self._maybe_emit(node)

    def visit_WhileStmt(self, node) -> None:
        self._maybe_emit(node)

    def visit_DoWhile(self, node) -> None:
        self._maybe_emit(node)

    def _maybe_emit(self, node) -> None:
        # The runner pushes the loop *before* dispatching, so the current
        # loop is this one; ``outer_loop()`` returns the enclosing loop
        # if any.
        # Dispatch invariant: only the six visit_<LoopKind> methods
        # above call this, so ``node`` is always a LOOP_TYPES instance.
        outer = self.ctx.outer_loop()
        if outer is None:
            return

        if _is_bounded(outer) and _is_bounded(node):
            self.ctx.emit(
                line=node.line,
                severity="info",
                message=(
                    "Nested loops both bounded by literal counters; "
                    "O(constant) — informational only "
                    f"(outer loop at line {outer.line}, inner loop at "
                    f"line {node.line})"
                ),
            )
            return

        if _contains_expensive_call(node.body):
            self.ctx.emit(
                line=node.line,
                severity="error",
                message=(
                    f"Nested loop with expensive call inside: outer loop "
                    f"at line {outer.line}, inner loop at line "
                    f"{node.line}"
                ),
            )
            return

        self.ctx.emit(
            line=node.line,
            message=(
                f"Nested loop detected: outer loop at line {outer.line}, "
                f"inner loop at line {node.line}"
            ),
        )


# ── SR031 helpers ──────────────────────────────────────────────────


# Built-ins whose calls are considered side-effectful / expensive.
# Method calls (``obj.something(...)``) are also treated as expensive
# regardless of name — see ``_contains_expensive_call``.
EXPENSIVE_FUNCTIONS: set[str] = {"getsqldata", "callservice"}

# Any built-in whose lowercased name starts with one of these prefixes
# is also expensive. Covers ``getObject``, ``getObjects``,
# ``getObjectIdByCode``, and future variants.
_EXPENSIVE_PREFIXES: tuple[str, ...] = ("getobject",)


def _is_bounded(loop_node: Node) -> bool:
    """True iff the loop's iteration count is provably bounded by a
    small constant.

    For now, only the ``for X := <num> to <num> do`` form qualifies.
    All other loops (counted ``downto``, ``foreach``, ``while``,
    ``do-while``, C-style ``for``) return ``False`` — an honest default
    we can refine later (e.g. literal-list ``foreach`` ranges).
    """
    if not isinstance(loop_node, ForCounter):
        return False
    return isinstance(loop_node.start, NumberLit) and isinstance(
        loop_node.end, NumberLit
    )


def _contains_expensive_call(node: Node) -> bool:
    """Walk ``node``'s subtree and return True on the first expensive
    call encountered.

    Expensive = a ``Call`` whose callee is either:
    - an ``Identifier`` whose lowercased name is in
      ``EXPENSIVE_FUNCTIONS`` or starts with any prefix in
      ``_EXPENSIVE_PREFIXES``;
    - a ``FieldAccess`` (i.e. a method call ``obj.method(...)``) — all
      method calls are conservatively treated as expensive for now.
    """
    if isinstance(node, Call):
        callee = node.callee
        if isinstance(callee, Identifier):
            name = callee.name.lower()
            if name in EXPENSIVE_FUNCTIONS:
                return True
            if any(name.startswith(p) for p in _EXPENSIVE_PREFIXES):
                return True
        elif isinstance(callee, FieldAccess):
            return True
    for child in node.children():
        if _contains_expensive_call(child):
            return True
    return False


# ── SR032 RepeatedQueryCheck ───────────────────────────────────────


_QUERY_FUNCTIONS: frozenset[str] = frozenset({"getsqldata", "getdata"})


@register_check(
    rule_id="SR032",
    category="performance",
    severity="warning",
    description=(
        "Duplicate or near-duplicate queries in the same rule, with "
        "graded severity (info / warning / error) and merge hints."
    ),
)
class RepeatedQueryCheck(Check):
    """Detect repeated SQL queries within a single BizRule.

    Implements SPEC §8 SR032. Three tiers, most-specific first:

    - **error (T1)**: same table, same SELECT fields, same WHERE
      conjuncts → the second call is fully redundant.
    - **warning (T2)**: same table, same WHERE, *different* SELECT
      fields → merge into one query selecting the union of fields.
    - **info (T3)**: same table, same SELECT, WHEREs differ only in
      the literal-equality value of exactly one column → merge with
      ``column IN (val1, val2)`` (and add the discriminating column
      to the SELECT if the consumer needs to tell rows apart).

    Both ``getSqlData(...)`` and ``getData(...)`` are query primitives
    in this language; both are checked. The check sees the AST after
    string concatenations have been flattened and after the rule's
    intra-script string assignments have been substituted, so the
    following forms are all recognised:

    - inline ``getSqlData("select ...")`` calls
    - string-concatenation builders (``"select ... " + idVal``)
    - mixed-case ``SELECT``
    - ``getData(...)`` calls
    """

    def visit_Script(self, node: Script) -> None:
        assigns = collect_string_assignments(node)
        sites: list[tuple[Call, ParsedQuery]] = []
        for call in _walk_calls(node):
            if not _is_query_call(call):
                continue
            if not call.args:
                continue
            sql = flatten_query_arg(call.args[0], assigns)
            parsed = parse_query(sql)
            if parsed is None:
                continue
            sites.append((call, parsed))

        # Pairwise compare. Each later call is reported at most once
        # (against its earliest match), so we mark "consumed" indices.
        consumed: set[int] = set()
        for j in range(1, len(sites)):
            if j in consumed:
                continue
            for i in range(j):
                tier = _classify_pair(sites[i][1], sites[j][1])
                if tier is None:
                    continue
                consumed.add(j)
                self._emit_tier(tier, sites[i][0], sites[j][0], sites[i][1], sites[j][1])
                break

    def _emit_tier(
        self,
        tier: str,
        first_call: Call,
        second_call: Call,
        first: ParsedQuery,
        second: ParsedQuery,
    ) -> None:
        if tier == "T1":
            self.ctx.emit(
                line=second_call.line,
                severity="error",
                message=(
                    f"Duplicate query at lines {first_call.line} and "
                    f"{second_call.line}: same table `{second.table}`, "
                    f"same SELECT fields, same WHERE — the second call "
                    f"is redundant"
                ),
            )
        elif tier == "T2":
            union = sorted(first.select_fields | second.select_fields)
            self.ctx.emit(
                line=second_call.line,
                severity="warning",
                message=(
                    f"Near-duplicate query at lines {first_call.line} "
                    f"and {second_call.line}: same table `{second.table}` "
                    f"and WHERE, different SELECT fields — consider "
                    f"merging into one query selecting "
                    f"{', '.join(union)}"
                ),
            )
        elif tier == "T3":
            diff = _single_value_diff(first.where_conjuncts, second.where_conjuncts)
            assert diff is not None  # _classify_pair already verified
            col, v1, v2 = diff
            self.ctx.emit(
                line=second_call.line,
                severity="info",
                message=(
                    f"Near-duplicate query at lines {first_call.line} "
                    f"and {second_call.line}: same table `{second.table}` "
                    f"and SELECT, WHERE differs only in `{col}` "
                    f"({v1} vs {v2}) — consider merging with "
                    f"`{col} IN ({v1}, {v2})` and adding `{col}` to "
                    f"the SELECT"
                ),
            )


def _walk_calls(root: Node):
    if isinstance(root, Call):
        yield root
    for child in root.children():
        yield from _walk_calls(child)


def _is_query_call(call: Call) -> bool:
    callee = call.callee
    if not isinstance(callee, Identifier):
        return False
    return callee.name.lower() in _QUERY_FUNCTIONS


def _classify_pair(a: ParsedQuery, b: ParsedQuery) -> str | None:
    """Return the tier label of the strongest match between ``a`` and
    ``b``, or ``None`` if they are not similar enough to flag.

    Most-specific first: T1 wins over T2 wins over T3.
    """
    if a.table != b.table:
        return None
    same_select = a.select_fields == b.select_fields
    same_where = a.where_conjuncts == b.where_conjuncts
    if same_select and same_where:
        return "T1"
    if same_where and not same_select:
        return "T2"
    if same_select and not same_where:
        if _single_value_diff(a.where_conjuncts, b.where_conjuncts) is not None:
            return "T3"
    return None


def _single_value_diff(
    a: tuple[Conjunct, ...], b: tuple[Conjunct, ...]
) -> tuple[str, str, str] | None:
    """If ``a`` and ``b`` differ in exactly one ``=`` conjunct on the
    same column, return ``(column, value_a, value_b)``. Otherwise
    ``None``.
    """
    if len(a) != len(b) or len(a) == 0:
        return None
    diffs: list[tuple[Conjunct, Conjunct]] = []
    # Conjuncts are sorted by (column, op, value) inside parse_query;
    # walk both in lockstep, recording mismatches.
    matched_b: set[int] = set()
    a_unmatched: list[Conjunct] = []
    for ca in a:
        for k, cb in enumerate(b):
            if k in matched_b:
                continue
            if ca == cb:
                matched_b.add(k)
                break
        else:
            a_unmatched.append(ca)
    b_unmatched = [cb for k, cb in enumerate(b) if k not in matched_b]
    if len(a_unmatched) != 1 or len(b_unmatched) != 1:
        return None
    ca, cb = a_unmatched[0], b_unmatched[0]
    if ca.column != cb.column:
        return None
    if ca.op != "=" or cb.op != "=":
        return None
    if ca.value == cb.value:
        return None
    return (ca.column, ca.value, cb.value)


# ── SR033 UnboundedLoopCheck ───────────────────────────────────────


@register_check(
    rule_id="SR033",
    category="performance",
    severity="warning",
    description="Unbounded or trivially infinite loop",
)
class UnboundedLoopCheck(Check):
    """Flag while / do-while / C-style for loops that cannot be shown
    to terminate.

    Implements SPEC §6 SR033. Two firing paths, both conservative:

    - **Trivially infinite**: the condition is a truthy literal —
      a non-zero ``NumberLit`` or a non-empty ``StringLit``. C-style
      ``for`` with a missing condition (``for ( ; ; )``) is treated
      the same way.
    - **Unbounded condition**: the set of identifier / field-access
      string-forms appearing in the condition is *disjoint* from the
      set of assignment targets in the loop body (and in the C-for
      step). Function and method calls in the body do **not** count
      as mutations — in this language, only ``:=`` and ``?=`` mutate
      a variable.

    ``foreach`` and counter-``for`` (``for X := a to b do``) are
    bounded by the language and are not visited.

    A condition with no extractable identifiers (e.g.
    ``while (getStatus())``) is silent — there is no signal to reason
    about and firing would be a false positive.
    """

    def visit_WhileStmt(self, node) -> None:
        self._check(node, node.cond, (node.body,))

    def visit_DoWhile(self, node) -> None:
        self._check(node, node.cond, (node.body,))

    def visit_ForCStyle(self, node) -> None:
        if node.cond is None:
            self.ctx.emit(
                line=node.line,
                message="C-style for has no termination condition",
            )
            return
        scopes = (node.body,) if node.step is None else (node.body, node.step)
        self._check(node, node.cond, scopes)

    def _check(
        self,
        loop_node: Node,
        cond: Expr,
        body_scopes: tuple[Node, ...],
    ) -> None:
        if _is_truthy_literal(cond):
            self.ctx.emit(
                line=loop_node.line,
                message="loop condition is a truthy literal",
            )
            return
        cond_vars = _collect_cond_vars(cond)
        if not cond_vars:
            # No identifier / field-access in the condition — nothing
            # we can structurally compare against the body.
            return
        assigned: set[str] = set()
        for scope in body_scopes:
            _collect_assigned_names(scope, assigned)
        if cond_vars.isdisjoint(assigned):
            names = ", ".join(sorted(cond_vars))
            self.ctx.emit(
                line=loop_node.line,
                message=(
                    f"condition variable(s) {{{names}}} not modified in body"
                ),
            )


# ── SR033 helpers ──────────────────────────────────────────────────


def _is_truthy_literal(expr: Expr) -> bool:
    """True for any non-zero NumberLit or any non-empty StringLit."""
    if isinstance(expr, NumberLit):
        return expr.value != 0
    if isinstance(expr, StringLit):
        return len(expr.value) > 0
    return False


def _dotted_name(expr: Node) -> str | None:
    """Return the string-form of an Identifier / FieldAccess chain.

    ``Identifier("x")`` → ``"x"``;
    ``FieldAccess(Identifier("obj"), "F")`` → ``"obj.F"``;
    nested chains (``a.b.c``) are joined with dots.
    Anything else returns ``None``.
    """
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, FieldAccess):
        target = _dotted_name(expr.target)
        if target is None:
            return None
        return f"{target}.{expr.field}"
    return None


def _collect_cond_vars(expr: Node) -> set[str]:
    """Walk ``expr`` collecting string-forms of every Identifier and
    FieldAccess appearing in it, except those in callee position.

    For a FieldAccess like ``obj.READY``, both ``"obj.READY"`` and
    ``"obj"`` are recorded — reassigning the whole object also counts
    as mutating ``obj.READY``.

    Function and method names (``Call.callee``) are NOT recorded —
    they are not variables that the body could mutate. ``Call`` args
    are walked normally.
    """
    out: set[str] = set()

    def walk(n: Node) -> None:
        if isinstance(n, Call):
            # Skip the callee; walk arguments only.
            for arg in n.args:
                walk(arg)
            return
        name = _dotted_name(n)
        if name is not None:
            out.add(name)
            if isinstance(n, FieldAccess):
                # Continue down so nested identifiers (``obj`` in
                # ``obj.READY``) are also captured as bare names.
                walk(n.target)
            return
        for child in n.children():
            walk(child)

    walk(expr)
    return out


def _collect_assigned_names(node: Node, out: set[str]) -> None:
    """Walk ``node``'s subtree adding string-forms of every
    AssignStmt target that is an Identifier or a FieldAccess.

    TableSelector / ArrayIndex targets are intentionally ignored —
    out of scope per the rule spec, and conservative (the disjoint
    test will be more likely to fire, but only on shapes we have not
    proven safe).
    """
    if isinstance(node, AssignStmt):
        name = _dotted_name(node.target)
        if name is not None:
            out.add(name)
    for child in node.children():
        _collect_assigned_names(child, out)


# SR034_MARKER

# ── SR034 RepeatedFieldReadCheck ───────────────────────────────────


from ._field_access import dotted_name as _ff_dotted_name  # noqa: E402
from ._field_access import field_key as _ff_field_key  # noqa: E402
from ._field_access import root_var as _ff_root_var  # noqa: E402


@register_check(
    rule_id="SR034",
    category="performance",
    severity="info",
    description=(
        "Repeated reads of the same field on the same object without "
        "intervening reassignment"
    ),
)
class RepeatedFieldReadCheck(Check):
    """Flag a second (or later) read of the same ``obj.field`` (or
    ``obj.sub.field``) when no reassignment to either the field or the
    leftmost root variable has happened between the two reads.

    Implements SPEC §6 SR034. Repeated field reads aren't *wrong* —
    they're just a missed opportunity: caching the value once in a
    local variable is both faster (skip whatever indirection
    ``obj.field`` triggers) and more readable (the local name documents
    the intent).

    Detection works by walking the script in source order, emitting
    three event kinds:

    - ``read(key)`` for every ``FieldAccess`` whose ``target`` is a
      bare-rooted dotted name (``getThing().F`` is skipped — no stable
      source to cache against). ``FieldAccess`` nodes used as the
      callee of a ``Call`` are NOT counted as reads: ``obj.method()``
      may have side effects or return different values per invocation,
      so two such calls aren't redundant the way two reads of
      ``obj.F`` are. Same exclusion as SR057/SR059.
    - ``var_assign(name)`` for every ``AssignStmt`` whose target is a
      bare ``Identifier`` — invalidates every cached group whose root
      equals ``name``;
    - ``field_assign(key)`` for every ``AssignStmt`` whose target is a
      ``FieldAccess`` — invalidates only that specific key.

    Reads of the same ``(target, field)`` key are accumulated into a
    *group*. A group is closed when an invalidating event fires for it
    or at end-of-script. A closed group with N≥2 reads produces
    exactly ONE finding, anchored at the FIRST read's line, listing
    every read line and the total count.

    Within a single statement, value-side reads are emitted **before**
    the target-side write so that ``obj.F := obj.F + 1`` does not
    self-invalidate (the read of ``obj.F`` on the RHS is processed
    before the write on the LHS).
    """

    def visit_Script(self, node: Script) -> None:
        events: list[tuple[str, object, int]] = []
        self._collect(node, events)

        groups: dict[tuple[str, str], list[int]] = {}

        def flush(key: tuple[str, str]) -> None:
            lines = groups.pop(key, [])
            if len(lines) < 2:
                return
            target_dotted, field = key
            line_list = ", ".join(str(l) for l in lines)
            self.ctx.emit(
                line=lines[0],
                message=(
                    f"Field '{target_dotted}.{field}' read "
                    f"{len(lines)} times (lines {line_list}) — "
                    "consider caching in a local variable to avoid "
                    "repeated lookups."
                ),
            )

        for kind, payload, _line in events:
            if kind == "var_assign":
                name = payload  # type: ignore[assignment]
                for k in list(groups):
                    if _ff_root_var(k[0]) == name:
                        flush(k)
            elif kind == "field_assign":
                key = payload  # type: ignore[assignment]
                flush(key)  # type: ignore[arg-type]
            elif kind == "read":
                key, rline = payload  # type: ignore[misc]
                groups.setdefault(key, []).append(rline)

        # End-of-script flush of any still-open groups.
        for key in list(groups):
            flush(key)

    # ── Event collection ────────────────────────────────────────

    def _collect(
        self,
        node: Node,
        events: list[tuple[str, object, int]],
    ) -> None:
        """Walk ``node`` in source order, appending events to ``events``."""
        if isinstance(node, AssignStmt):
            # Process value (reads) first, then target (writes).
            self._collect_read(node.value, events)
            self._collect_write_target(node.target, node.line, events)
            return
        # All other node kinds: just collect reads.
        self._collect_read(node, events)

    def _collect_read(
        self,
        node: Node,
        events: list[tuple[str, object, int]],
    ) -> None:
        if isinstance(node, Call):
            # Callee in call position: don't count as a read. Methods
            # may have side effects / per-invocation results, so two
            # ``obj.method()`` calls aren't redundant. Still walk into
            # the callee's receiver chain so nested reads (e.g.
            # ``obj.sub`` inside ``obj.sub.method()``) are tracked.
            if isinstance(node.callee, FieldAccess):
                self._collect_read(node.callee.target, events)
            else:
                self._collect_read(node.callee, events)
            for arg in node.args:
                self._collect_read(arg, events)
            return
        if isinstance(node, FieldAccess):
            key = _ff_field_key(node)
            if key is not None:
                events.append(("read", (key, node.line), node.line))
            # Walk into target so nested reads (``obj.sub`` inside
            # ``obj.sub.F``) are also tracked.
            self._collect_read(node.target, events)
            return
        if isinstance(node, AssignStmt):
            # Re-enter the assign-aware path so nested AssignStmts
            # inside expressions (rare, but possible via ``?=``-bearing
            # forms in the future) are still classified correctly.
            self._collect(node, events)
            return
        for child in node.children():
            self._collect_read(child, events)

    def _collect_write_target(
        self,
        target: Expr,
        stmt_line: int,
        events: list[tuple[str, object, int]],
    ) -> None:
        if isinstance(target, Identifier):
            events.append(("var_assign", target.name, stmt_line))
            return
        if isinstance(target, FieldAccess):
            key = _ff_field_key(target)
            if key is not None:
                events.append(("field_assign", key, stmt_line))
            # The target's own ``target`` (intermediate object in
            # ``obj.sub.F := v``) is read context, not a write.
            self._collect_read(target.target, events)
            return
        # TableSelector / ArrayIndex / etc. — not tracked as a write
        # for SR034 purposes (SR058 owns auto-create on TableSelector).
        # Still walk into them so reads inside conditions/indices are
        # captured.
        self._collect_read(target, events)
