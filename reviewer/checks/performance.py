"""Performance checks (SR030..SR034)."""
from __future__ import annotations

from ..ast.nodes import (
    Call,
    FieldAccess,
    ForCounter,
    Identifier,
    Node,
    NumberLit,
)
from ..engine.registry import register_check
from ..engine.visitor import Check


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
