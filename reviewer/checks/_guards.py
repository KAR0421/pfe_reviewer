"""Helpers for checks that reason about *guards* — boolean expressions
in ``IfStmt`` conditions whose role is to make a subsequent statement
safe.

Currently used by SR058 (unintended record auto-create). The helpers
are module-level so that future flow-sensitive checks
(SR042 null-guarded field access, future SR041 div-by-zero refinement)
can share the structural-equality and comparison-classification logic.
"""
from __future__ import annotations

from ..ast.nodes import (
    BinaryOp,
    Call,
    Expr,
    FieldAccess,
    Identifier,
    NumberLit,
    StringLit,
    TableSelector,
    UnaryOp,
)


# ── Structural equality ────────────────────────────────────────────


def expr_eq(a: Expr, b: Expr) -> bool:
    """Recursive structural equality on expression nodes.

    Two expressions are equal when they have the same node type and
    every component matches recursively. ``StringLit`` ignores the
    ``quote`` field — ``""`` and ``''`` are the same value.

    Used by SR058 to decide "is the TableSelector in this assignment
    the same one referenced in the enclosing if-condition?"
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, Identifier):
        return a.name == b.name  # type: ignore[union-attr]
    if isinstance(a, NumberLit):
        return a.value == b.value  # type: ignore[union-attr]
    if isinstance(a, StringLit):
        return a.value == b.value  # type: ignore[union-attr]
    if isinstance(a, FieldAccess):
        b_fa: FieldAccess = b  # type: ignore[assignment]
        return a.field == b_fa.field and expr_eq(a.target, b_fa.target)
    if isinstance(a, TableSelector):
        return tableselector_structural_eq(a, b)  # type: ignore[arg-type]
    if isinstance(a, BinaryOp):
        b_bo: BinaryOp = b  # type: ignore[assignment]
        return (
            a.op == b_bo.op
            and expr_eq(a.left, b_bo.left)
            and expr_eq(a.right, b_bo.right)
        )
    if isinstance(a, UnaryOp):
        b_uo: UnaryOp = b  # type: ignore[assignment]
        return a.op == b_uo.op and expr_eq(a.operand, b_uo.operand)
    if isinstance(a, Call):
        b_call: Call = b  # type: ignore[assignment]
        if not expr_eq(a.callee, b_call.callee):
            return False
        if len(a.args) != len(b_call.args):
            return False
        return all(expr_eq(x, y) for x, y in zip(a.args, b_call.args))
    return False


def tableselector_structural_eq(a: TableSelector, b: TableSelector) -> bool:
    """Recursive structural equality for ``TableSelector`` nodes:
    same target, same field name, same condition expression.
    """
    if not (isinstance(a, TableSelector) and isinstance(b, TableSelector)):
        return False
    return (
        a.field == b.field
        and expr_eq(a.target, b.target)
        and expr_eq(a.condition, b.condition)
    )


# ── Comparison classification ──────────────────────────────────────


# Classifications, ordered by how strongly they suppress an SR058
# finding when found in an enclosing if-condition.
EMPTINESS_CHECK = "EMPTINESS_CHECK"
PRESENCE_CHECK = "PRESENCE_CHECK"
VALUE_ENGAGEMENT = "VALUE_ENGAGEMENT"


_RANK: dict[str | None, int] = {
    None: 0,
    EMPTINESS_CHECK: 1,
    PRESENCE_CHECK: 2,
    VALUE_ENGAGEMENT: 3,
}


def _is_null(e: Expr) -> bool:
    """``Identifier`` whose name is ``"null"`` (case-insensitive)."""
    return isinstance(e, Identifier) and e.name.lower() == "null"


def _is_empty_string(e: Expr) -> bool:
    """``StringLit`` whose value is the empty string (either quote style)."""
    return isinstance(e, StringLit) and e.value == ""


def _is_empty_marker(e: Expr) -> bool:
    return _is_null(e) or _is_empty_string(e)


def classify_comparison(cond: Expr, ts: TableSelector) -> str | None:
    """Classify how the ``TableSelector`` ``ts`` is referenced inside
    the boolean expression ``cond``.

    Returns one of ``EMPTINESS_CHECK``, ``PRESENCE_CHECK``,
    ``VALUE_ENGAGEMENT``, or ``None`` (``ts`` is not referenced in
    ``cond`` at all). Used by SR058 to decide whether an enclosing
    ``IfStmt`` covers an assignment to ``ts``:

    - **EMPTINESS_CHECK** — ``ts = null``, ``ts = ""``, or ``! ts``.
      The condition is true exactly when the row is missing.
    - **PRESENCE_CHECK** — ``ts != null``, ``ts != ""``, or bare ``ts``.
      The condition is true exactly when the row is present.
    - **VALUE_ENGAGEMENT** — any other comparison that touches ``ts``
      (``ts = "VALIDATED"``, ``ts > 5``, ``ts != someVar``, …). The
      developer reads the value, implicitly asserting it exists; the
      assignment is safe in either branch.

    For boolean combinators (``and`` / ``or``), recurse into both
    operands and return the strongest classification found, where
    ``VALUE_ENGAGEMENT`` > ``PRESENCE_CHECK`` > ``EMPTINESS_CHECK``.
    Strength is defined as "most likely to leave the assignment
    silent": the most permissive classification wins, because adding
    extra clauses to a condition shouldn't *create* a finding that
    a simpler version of the same guard wouldn't have produced.
    """
    # ── ``and`` / ``or``: combine sub-classifications. ──
    if isinstance(cond, BinaryOp) and cond.op.lower() in ("and", "or"):
        left = classify_comparison(cond.left, ts)
        right = classify_comparison(cond.right, ts)
        return _strongest(left, right)

    # ── Unary not: invert a presence/emptiness classification. ──
    # The language has no ``!`` token; logical negation is the
    # built-in call ``not(expr)``. We also accept ``UnaryOp("!", ...)``
    # defensively in case the grammar gains a unary-not later.
    if isinstance(cond, UnaryOp) and cond.op == "!":
        inner = cond.operand
        return _invert(_classify_inner(inner, ts))
    if (
        isinstance(cond, Call)
        and isinstance(cond.callee, Identifier)
        and cond.callee.name.lower() == "not"
        and len(cond.args) == 1
    ):
        return _invert(_classify_inner(cond.args[0], ts))

    # ── Direct comparison: classify based on op + the *other* side. ──
    if isinstance(cond, BinaryOp) and cond.op in {
        "=",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
    }:
        if isinstance(cond.left, TableSelector) and tableselector_structural_eq(
            cond.left, ts
        ):
            other = cond.right
        elif isinstance(
            cond.right, TableSelector
        ) and tableselector_structural_eq(cond.right, ts):
            other = cond.left
        else:
            return None
        if cond.op == "=":
            return EMPTINESS_CHECK if _is_empty_marker(other) else VALUE_ENGAGEMENT
        if cond.op == "!=":
            return PRESENCE_CHECK if _is_empty_marker(other) else VALUE_ENGAGEMENT
        # <, <=, >, >= — value comparison, asserts presence implicitly.
        return VALUE_ENGAGEMENT

    # ── Bare TS as the entire condition: presence/truthy check. ──
    if isinstance(cond, TableSelector) and tableselector_structural_eq(cond, ts):
        return PRESENCE_CHECK

    return None


def _strongest(a: str | None, b: str | None) -> str | None:
    """Return whichever classification has the higher rank."""
    return a if _RANK[a] >= _RANK[b] else b


def _classify_inner(inner: Expr, ts: TableSelector) -> str | None:
    """Classify the operand of a ``not(...)`` / ``!`` wrapper.

    Bare-TS inside negation is an EMPTINESS_CHECK directly
    (``not(TS)`` / ``!TS`` ≡ "TS is missing"). Anything else is
    classified normally so the outer ``_invert`` call can flip it.
    """
    if isinstance(inner, TableSelector) and tableselector_structural_eq(
        inner, ts
    ):
        # ``not(TS)`` reads as PRESENCE_CHECK on the inner side; the
        # outer ``_invert`` will flip it to EMPTINESS_CHECK.
        return PRESENCE_CHECK
    return classify_comparison(inner, ts)


def _invert(cls: str | None) -> str | None:
    """Swap PRESENCE ↔ EMPTINESS; leave VALUE_ENGAGEMENT and None alone."""
    if cls == PRESENCE_CHECK:
        return EMPTINESS_CHECK
    if cls == EMPTINESS_CHECK:
        return PRESENCE_CHECK
    return cls


# ── Source-style reconstruction ────────────────────────────────────


def expr_repr(e: Expr) -> str:
    """Best-effort source-shaped string for ``e``.

    Used in finding messages so reviewers can identify the offending
    expression at a glance without re-reading source. Not source-exact
    — operator spacing and parenthesisation may differ — but stable
    enough for grep and review.
    """
    if isinstance(e, Identifier):
        return e.name
    if isinstance(e, NumberLit):
        return e.raw
    if isinstance(e, StringLit):
        return f"{e.quote}{e.value}{e.quote}"
    if isinstance(e, FieldAccess):
        return f"{expr_repr(e.target)}.{e.field}"
    if isinstance(e, TableSelector):
        return (
            f"{expr_repr(e.target)}.{e.field}[{expr_repr(e.condition)}]"
        )
    if isinstance(e, BinaryOp):
        return f"{expr_repr(e.left)} {e.op} {expr_repr(e.right)}"
    if isinstance(e, UnaryOp):
        return f"{e.op}{expr_repr(e.operand)}"
    if isinstance(e, Call):
        return f"{expr_repr(e.callee)}(...)"
    return "?"
