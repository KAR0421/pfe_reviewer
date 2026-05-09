"""Performance checks (SR030..SR034)."""
from __future__ import annotations

from ..ast.nodes import (
    Call,
    FieldAccess,
    ForCounter,
    Identifier,
    Node,
    NumberLit,
    Script,
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

    Weaknesses of the legacy regex-based version that this fixes:
    - The legacy scanner matches ``for``/``while``/``do`` substrings
      inside comments and string literals.
    - ``do { ... } while (...)`` was double-counted because the legacy
      stack pushed on both the ``do`` line and the trailing ``while``.
    - Brace de-sync: a ``}`` closing an ``if`` body popped a loop
      frame, yielding off-by-one nesting reports.

    The AST version uses the runner-maintained loop stack
    (``CheckContext._loop_stack``).
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

    Implements SPEC §8 SR032 as a substantial expansion of the legacy
    ``check_repeated_queries`` (which only catched exact duplicates of
    queries assembled into a variable and passed to ``getSqlData``).

    Three tiers, most-specific first:

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
    intra-script string assignments have been substituted, so it
    catches the legacy's many false negatives:

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

