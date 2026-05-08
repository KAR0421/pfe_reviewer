"""Static-logic checks (SR020..SR022).

Currently implements:
- SR020 static / always-true-or-false conditions.
- SR021 dead code after ``return`` / ``abort`` / ``skip``.
"""
from __future__ import annotations

from reviewer.ast.nodes import (
    AbortStmt,
    ArrayIndex,
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

    The legacy ``check_dead_code`` worked line-by-line over the raw
    script and produced false positives on:
    - ``return``/``abort``/``skip`` literals appearing in comments or
      inside string literals;
    - ``if (x) return;`` followed by an ``else`` branch (legacy flagged
      the ``else`` as dead);
    - one-liner forms (multiple statements on the same line).

    The AST version is structural: it inspects the statement list of
    every ``Block`` and ``Script`` and only fires when a terminator is
    not the last sibling — comments and strings have already been
    stripped by the tokenizer, and ``if``/``else`` branches are distinct
    sub-blocks.
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
        # Convention (matches legacy `check_dead_code`): the finding's
        # ``line`` field points at the *terminator*, not the successor —
        # that's the location a developer needs to fix. The successor's
        # line is named in the message for context.
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

    Why this is better than the regex form in ``reviewer_legacy``:
    - Comments and string literals are already gone by the time we see
      the AST, so ``// if (1 = 1)`` and ``"if (1 = 1)"`` no longer
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
