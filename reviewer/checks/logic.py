"""Static-logic checks (SR020..SR022).

Currently implements:
- SR020 static / always-true-or-false conditions.
- SR021 dead code after ``return`` / ``abort`` / ``skip``.
"""
from __future__ import annotations

from dataclasses import dataclass

from reviewer.ast.nodes import (
    AbortStmt,
    ArrayIndex,
    AssignStmt,
    BinaryOp,
    Block,
    Call,
    Expr,
    FieldAccess,
    ForCStyle,
    Identifier,
    IfStmt,
    Node,
    NumberLit,
    ReturnStmt,
    Script,
    SkipStmt,
    StringLit,
    TableSelector,
    UnaryOp,
    DoWhile,
    WhileStmt,
)
from reviewer.engine.registry import register_check
from reviewer.engine.visitor import Check


# Terminators: any of these statements ends control flow for the
# enclosing block. Anything that follows in the *same* statement list
# is unreachable.
_TERMINATORS = (ReturnStmt, AbortStmt, SkipStmt)
_TERMINATOR_NAMES = {
    ReturnStmt: "return",
    AbortStmt: "abort",
    SkipStmt: "skip",
}


@register_check(
    rule_id="SR021",
    category="logic",
    severity="warning",
    description="Dead code after `return` / `abort` / `skip`.",
)
class DeadCodeCheck(Check):
    """Flag the first statement following a terminator within a block.

    Implements SPEC §8 row SR021: ``return``/``abort``/``skip`` end
    control flow; any statement that follows them in the same statement
    list is unreachable.

    The check is structural: it inspects the statement list of every
    ``Block`` and ``Script`` and only fires when a terminator is not
    the last sibling. Comments and strings have already been stripped
    by the tokenizer, and ``if``/``else`` branches are distinct
    sub-blocks, so terminator literals inside comments/strings or a
    ``return`` in a then-branch followed by an ``else`` branch do not
    fire.
    """

    def visit_Script(self, node: Script) -> None:
        self._scan_statements(node.statements)

    def visit_Block(self, node: Block) -> None:
        self._scan_statements(node.statements)

    def _scan_statements(self, stmts) -> None:
        # Walk pairwise; a terminator that is not the last statement of
        # its parent block makes its successor unreachable. We flag only
        # the immediate successor — once reported, downstream statements
        # are obviously unreachable too and reporting them all would be
        # noise.
        #
        # Convention: the finding's ``line`` field points at the
        # *terminator*, not the successor — that's the location a
        # developer needs to fix. The successor's line is named in the
        # message for context.
        for i, stmt in enumerate(stmts[:-1]):
            if isinstance(stmt, _TERMINATORS):
                successor = stmts[i + 1]
                term_name = _TERMINATOR_NAMES[type(stmt)]
                self.ctx.emit(
                    line=stmt.line,
                    message=(
                        f"Dead code after '{term_name}': next statement "
                        f"on line {successor.line} is unreachable"
                    ),
                )


# ── SR020 StaticConditionCheck ─────────────────────────────────────


_COMPARISON_OPS = {"=", "!=", "<", "<=", ">", ">="}
_LOGICAL_OPS = {"and", "or"}


def _is_literal(node: object) -> bool:
    return isinstance(node, (NumberLit, StringLit))


def _ast_equal(a: object, b: object) -> bool:
    """Structural equality of two ``Expr`` subtrees, ignoring ``line``.

    Frozen-dataclass ``__eq__`` compares all fields including ``line``,
    so two ``obj.F`` references on different lines wouldn't match. This
    walker compares only the semantically meaningful fields.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, Identifier):
        return a.name == b.name
    if isinstance(a, NumberLit):
        return a.value == b.value
    if isinstance(a, StringLit):
        return a.value == b.value
    if isinstance(a, FieldAccess):
        return a.field == b.field and _ast_equal(a.target, b.target)
    if isinstance(a, ArrayIndex):
        return _ast_equal(a.array, b.array) and _ast_equal(a.index, b.index)
    if isinstance(a, Call):
        if len(a.args) != len(b.args):
            return False
        if not _ast_equal(a.callee, b.callee):
            return False
        return all(_ast_equal(x, y) for x, y in zip(a.args, b.args))
    if isinstance(a, BinaryOp):
        return (
            a.op == b.op
            and _ast_equal(a.left, b.left)
            and _ast_equal(a.right, b.right)
        )
    if isinstance(a, UnaryOp):
        return a.op == b.op and _ast_equal(a.operand, b.operand)
    if isinstance(a, TableSelector):
        return (
            a.field == b.field
            and _ast_equal(a.target, b.target)
            and _ast_equal(a.condition, b.condition)
        )
    return False


def _classify_condition(expr: Expr) -> str | None:
    """Return a kind tag if ``expr`` is statically suspicious, else None.

    Kinds:
    - ``always_true_or_false`` — comparison with literals on both sides.
    - ``self_compare`` — comparison whose two operands are
      structurally identical (``x = x``, ``f(a) = f(a)``, …).
    - ``only_literal`` — the entire condition is a single literal.
    - ``trivial_subcondition`` — ``and``/``or`` whose recursive walk
      contains a literal-vs-literal comparison or a self-compare.

    A bare ``Identifier`` returns ``None``: ``if (x)`` is the idiomatic
    truthy/null-check form in this language.
    """
    if isinstance(expr, BinaryOp) and expr.op in _COMPARISON_OPS:
        if _is_literal(expr.left) and _is_literal(expr.right):
            return "always_true_or_false"
        if _ast_equal(expr.left, expr.right):
            return "self_compare"
        return None
    if isinstance(expr, BinaryOp) and expr.op in _LOGICAL_OPS:
        if _classify_condition(expr.left) is not None:
            return "trivial_subcondition"
        if _classify_condition(expr.right) is not None:
            return "trivial_subcondition"
        return None
    if _is_literal(expr):
        return "only_literal"
    return None


_KIND_MESSAGES = {
    "always_true_or_false": (
        "Static condition (always true/false): both sides are literals"
    ),
    "self_compare": "Self-comparison: same expression on both sides of '{op}'",
    "only_literal": "Condition is a single literal",
    "trivial_subcondition": (
        "Trivially-static sub-condition inside 'and'/'or' "
        "(literal-vs-literal or self-compare)"
    ),
}


@register_check(
    rule_id="SR020",
    category="logic",
    severity="error",
    description="Static / always true-or-false condition.",
)
class StaticConditionCheck(Check):
    """Flag ``if``/``while``/``do-while``/``for`` conditions that are
    statically constant (or trivially so).

    Working at the AST level means:
    - Comments and string literals are already gone by the time we see
      the AST, so ``// if (1 = 1)`` and ``"if (1 = 1)"`` do not
      produce false positives.
    - We compare expression *trees*, not raw text, so ``(x) = x``,
      ``obj.F = obj.F``, and ``f(x) = f(x)`` are all detected.
    - ``and``/``or`` are walked recursively, so ``1 = 1 and x`` is
      caught — leftover debug code is loud, not redeemed by the live
      side.
    """

    def visit_IfStmt(self, node: IfStmt) -> None:
        self._check(node.cond)

    def visit_WhileStmt(self, node: WhileStmt) -> None:
        self._check(node.cond)

    def visit_DoWhile(self, node: DoWhile) -> None:
        self._check(node.cond)

    def visit_ForCStyle(self, node: ForCStyle) -> None:
        if node.cond is not None:
            self._check(node.cond)

    def _check(self, expr: Expr) -> None:
        kind = _classify_condition(expr)
        if kind is None:
            return
        template = _KIND_MESSAGES[kind]
        op = expr.op if isinstance(expr, BinaryOp) else ""
        self.ctx.emit(line=expr.line, message=template.format(op=op))


# ── SR041 DivByZeroCheck ──────────────────────────────────────────


from ._guards import (  # noqa: E402
    KNOWN_NONZERO,
    KNOWN_ZERO,
    UNKNOWN,
    classify_numeric_guard,
    expr_repr,
)


@register_check(
    rule_id="SR041",
    category="logic",
    severity="error",
    description="Division where the right operand could be zero.",
)
class DivByZeroCheck(Check):
    """Flag a ``BinaryOp(op="/")`` whose right operand is provably or
    possibly zero at the division line.

    Implements SPEC §6 SR041. Two severity tiers:

    - **error** (``KNOWN_ZERO``): the right operand is provably zero
      in this branch — either a literal ``0``, or guarded by an
      enclosing ``if (Y = 0) { ... }`` / ``if (Y != 0) { } else { ... }``
      / ``if (! Y) { ... }`` / etc.
    - **warning** (``UNKNOWN``): no enclosing guard establishes either
      side. The division might crash if ``Y`` is zero at runtime.
    - silent (``KNOWN_NONZERO``): a literal non-zero, or an enclosing
      guard proves ``Y`` is non-zero (``Y != 0``, ``Y > 0``, ``Y < 0``,
      ``Y >= 1``, bare-truthy ``Y``, value-engagement comparison such
      as ``Y = "ACTIVE"``).
    - silent (Call right-hand side): conservative skip — the check
      cannot reason about function return values.

    Guard analysis walks ``self.ctx.if_stack`` from innermost outward
    and uses the first frame that mentions the divisor. Compound
    conditions (``and`` / ``or``) currently short-circuit to
    ``UNKNOWN``; refine if real packs need it.
    """

    def visit_BinaryOp(self, node: BinaryOp) -> None:
        if node.op != "/":
            return
        right = node.right

        # Literal divisor: decide immediately.
        if isinstance(right, NumberLit):
            if right.value == 0:
                self._fire_error(node)
            return

        # Conservative skip for function-call divisors.
        if isinstance(right, Call):
            return

        # Identifier / FieldAccess / ArrayIndex / TableSelector — walk
        # the if-stack innermost outward; first frame that mentions
        # the divisor decides.
        verdict = UNKNOWN
        for frame in reversed(self.ctx.if_stack):
            cls = classify_numeric_guard(frame.cond, right, frame.branch)
            if cls is None:
                continue
            verdict = cls
            break

        if verdict == KNOWN_NONZERO:
            return
        if verdict == KNOWN_ZERO:
            self._fire_error(node)
            return
        # UNKNOWN — possibly zero at runtime.
        self._fire_warning(node)

    def _fire_error(self, node: BinaryOp) -> None:
        self.ctx.emit(
            line=node.line,
            message=(
                f"Division by zero at line {node.line}: "
                f"'{expr_repr(node.left)} / {expr_repr(node.right)}'. "
                "The right operand is provably zero in this branch."
            ),
        )

    def _fire_warning(self, node: BinaryOp) -> None:
        self.ctx.emit(
            line=node.line,
            severity="warning",
            message=(
                f"Division at line {node.line}: "
                f"'{expr_repr(node.left)} / {expr_repr(node.right)}'. "
                "The right operand is not guarded against zero — if "
                "it can be zero at runtime, the rule will crash."
            ),
        )


# ── SR042 UnverifiedObjectCheck ────────────────────────────────────


from ._guards import (  # noqa: E402
    EMPTINESS_CHECK,
    PRESENCE_CHECK,
    VALUE_ENGAGEMENT,
    classify_comparison,
)


# Built-in callees documented to potentially return null/empty/no-row.
# A bare-Identifier assignment whose RHS is a ``Call`` to one of these
# names tags the LHS as "fallible-typed" — its existence is unverified
# until guarded. Names are matched case-sensitively (NeoXam built-ins
# use camelCase).
FALLIBLE_OBJECT_SOURCES: frozenset[str] = frozenset({
    "getObject",
    "getObjects",
    "getObjectIdByCode",
    "getSqlData",
    "getData",
    "findRecord",
})


@dataclass
class _IfFrame:
    """Lightweight if-frame used by SR042's whole-script walker.

    SR042 cannot rely on ``ctx.if_stack`` because it runs the whole
    analysis from a single ``visit_Script`` call — it needs its own
    flow-tracked stack maintained while it walks the AST in source
    order.
    """

    cond: Expr
    branch: str  # "then" or "else"


@register_check(
    rule_id="SR042",
    category="logic",
    severity="warning",
    description=(
        "Object obtained from a fallible source is used without a "
        "prior existence check"
    ),
)
class UnverifiedObjectCheck(Check):
    """Flag the first unguarded use of an object obtained from a
    fallible NeoXam built-in (``getObject``, ``getObjects``,
    ``getObjectIdByCode``, ``getSqlData``, ``getData``,
    ``findRecord``) or from a ``TableSelector`` RHS.

    Implements SPEC §6 SR042. Replaces the old SR058
    ``AutoCreateAssignCheck`` with a single existence-check at the
    object level: per-operation flagging was too noisy. The new
    contract is "check the object once, use it freely after."

    Whole-script analysis. Two passes:

    1. **Collect** — scan every ``AssignStmt`` whose target is a bare
       ``Identifier``. If the RHS is a ``Call`` whose callee name is in
       ``FALLIBLE_OBJECT_SOURCES``, or a ``TableSelector``, the LHS
       name becomes a *fallible identifier* — its existence is
       unverified until guarded. The first fallible assignment per
       name wins (used in the warning message).

    2. **Walk** — single source-order walk maintaining an internal
       if-frame stack and a monotonic ``fired`` set:

       - At each ``FieldAccess`` whose root identifier is a fallible
         identifier not already in ``fired``, classify under the
         current if-stack via ``classify_comparison`` (innermost
         outward; first frame that mentions the identifier decides):

         - ``PRESENCE_CHECK`` then-branch / ``EMPTINESS_CHECK``
           else-branch / ``VALUE_ENGAGEMENT`` either branch →
           *KNOWN_PRESENT* → silent.
         - ``EMPTINESS_CHECK`` then-branch / ``PRESENCE_CHECK``
           else-branch → *KNOWN_NULL* → fire **error**, add to
           ``fired``.
         - No frame mentions the identifier → *UNKNOWN* → fire
           **warning**, add to ``fired``.

       - The ``fired`` set is monotonic across the whole script —
         once a finding has been emitted for an object, subsequent
         dereferences anywhere in the same script are silent. Same
         object, same risk class, already reported.

    A "use" of identifier ``X`` is any ``FieldAccess`` whose root
    target chain ends in ``Identifier(X)`` — read ``X.F``, write
    ``X.F := v`` (the AssignStmt's target is walked as a sub-expression),
    method call ``X.method()`` (``Call.callee`` is the FieldAccess),
    nested chain ``X.first.NAME`` (the inner FieldAccess root is ``X``).
    Bare ``Identifier(X)`` as a comparison operand or as a function
    argument is **not** a use — it's a check or a pass-through.

    Limitations (intentional, v1):

    - **Direct fallibility only.** ``y := x`` where ``x`` is a fallible
      identifier does *not* propagate fallibility to ``y``. A future
      refinement may track aliasing.
    - **Reassignment doesn't clear fallibility.** ``obj := getObject(); obj := 5; log(obj.F)``
      still flags the dereference even though ``obj`` is now an int.
      Unusual pattern; refine if real packs trip on it.
    - **``foreach`` loop variables are silent.** They are not
      introduced by an explicit ``AssignStmt``, so they are never
      added to the fallible set.
    - **Compound ``and``/``or`` guard conditions** inherit
      ``classify_comparison``'s "strongest classification wins"
      behaviour: a compound that includes a presence-check on the
      object will silence in the then-branch.
    """

    def visit_Script(self, node: Script) -> None:
        fallible: dict[str, tuple[int, str]] = {}
        self._collect_fallible(node, fallible)
        if not fallible:
            return
        if_stack: list[_IfFrame] = []
        fired: set[str] = set()
        for child in node.children():
            self._walk(child, fallible, if_stack, fired)

    def _collect_fallible(
        self, node: Node, fallible: dict[str, tuple[int, str]]
    ) -> None:
        if isinstance(node, AssignStmt) and isinstance(
            node.target, Identifier
        ):
            name = node.target.name
            if name not in fallible:
                label = self._fallible_label(node.value)
                if label is not None:
                    fallible[name] = (node.line, label)
        for child in node.children():
            self._collect_fallible(child, fallible)

    def _fallible_label(self, expr: Expr) -> str | None:
        if (
            isinstance(expr, Call)
            and isinstance(expr.callee, Identifier)
            and expr.callee.name in FALLIBLE_OBJECT_SOURCES
        ):
            return f"{expr.callee.name}(...)"
        if isinstance(expr, TableSelector):
            return expr_repr(expr)
        return None

    def _walk(
        self,
        node: Node,
        fallible: dict[str, tuple[int, str]],
        if_stack: list[_IfFrame],
        fired: set[str],
    ) -> None:
        # Branch handling: walk the cond (uses inside it count!), then
        # push a frame for each branch and recurse with that frame on
        # the stack.
        if isinstance(node, IfStmt):
            self._walk(node.cond, fallible, if_stack, fired)
            if_stack.append(_IfFrame(node.cond, "then"))
            try:
                self._walk(node.then_branch, fallible, if_stack, fired)
            finally:
                if_stack.pop()
            if node.else_branch is not None:
                if_stack.append(_IfFrame(node.cond, "else"))
                try:
                    self._walk(node.else_branch, fallible, if_stack, fired)
                finally:
                    if_stack.pop()
            return

        # Use detection: any FieldAccess whose root identifier is a
        # not-yet-fired fallible identifier.
        if isinstance(node, FieldAccess):
            root = self._root_identifier(node)
            if (
                root is not None
                and root.name in fallible
                and root.name not in fired
            ):
                self._handle_use(root.name, node, fallible, if_stack, fired)

        for child in node.children():
            self._walk(child, fallible, if_stack, fired)

    def _root_identifier(self, expr: Expr) -> Identifier | None:
        """Walk down a FieldAccess chain until we find the leaf
        target. Returns the Identifier if the chain bottoms out in
        one, else None.
        """
        cur: Expr = expr
        while isinstance(cur, FieldAccess):
            cur = cur.target
        return cur if isinstance(cur, Identifier) else None

    def _handle_use(
        self,
        name: str,
        use_expr: FieldAccess,
        fallible: dict[str, tuple[int, str]],
        if_stack: list[_IfFrame],
        fired: set[str],
    ) -> None:
        target = Identifier(name=name)
        decided: str | None = None  # "PRESENT" or "NULL"
        guard_line: int = 0
        for frame in reversed(if_stack):
            cls = classify_comparison(frame.cond, target)
            if cls is None:
                continue
            guard_line = frame.cond.line
            if cls == VALUE_ENGAGEMENT:
                decided = "PRESENT"
                break
            if cls == EMPTINESS_CHECK:
                decided = "NULL" if frame.branch == "then" else "PRESENT"
                break
            if cls == PRESENCE_CHECK:
                decided = "PRESENT" if frame.branch == "then" else "NULL"
                break

        if decided == "PRESENT":
            return

        src_line, src_label = fallible[name]
        if decided == "NULL":
            self.ctx.emit(
                line=use_expr.line,
                severity="error",
                message=(
                    f"Object '{name}' is used at line {use_expr.line} "
                    f"in a branch where the enclosing guard (line "
                    f"{guard_line}) proves it is null/empty. This "
                    "will crash."
                ),
            )
        else:
            self.ctx.emit(
                line=use_expr.line,
                severity="warning",
                message=(
                    f"Object '{name}' (obtained from `{src_label}` at "
                    f"line {src_line}) is used at line {use_expr.line} "
                    "without an existence check. If the source "
                    "returned null, this will crash."
                ),
            )
        fired.add(name)

