"""Helpers for checks that reason about *guards* — boolean expressions
in ``IfStmt`` conditions whose role is to make a subsequent statement
safe.

Currently used by SR042 (unverified-object existence check) and
SR041 (div-by-zero). The helpers
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

    Used by SR042 to decide "is the object referenced at this use
    site the same one referenced in the enclosing if-condition?"
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


# Classifications, ordered by how strongly they suppress an SR042
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


def classify_comparison(cond: Expr, target: Expr) -> str | None:
    """Classify how the expression ``target`` is referenced inside
    the boolean expression ``cond``.

    ``target`` is matched structurally via ``expr_eq``, so it works
    for any expression — a bare ``Identifier`` (used by SR042 to
    track null-guarded objects), a ``TableSelector``, a ``FieldAccess``,
    etc.

    Returns one of ``EMPTINESS_CHECK``, ``PRESENCE_CHECK``,
    ``VALUE_ENGAGEMENT``, or ``None`` (``target`` is not referenced in
    ``cond`` at all):

    - **EMPTINESS_CHECK** — ``target = null``, ``target = ""``, or
      ``not(target)``. The condition is true exactly when the value is
      missing/empty/null.
    - **PRESENCE_CHECK** — ``target != null``, ``target != ""``, or
      bare ``target``. The condition is true exactly when the value
      is present.
    - **VALUE_ENGAGEMENT** — any other comparison that touches
      ``target`` (``target = "VALIDATED"``, ``target > 5``,
      ``target != someVar``, …). The developer reads the value,
      implicitly asserting it exists.

    For boolean combinators (``and`` / ``or``), recurse into both
    operands and return the strongest classification found, where
    ``VALUE_ENGAGEMENT`` > ``PRESENCE_CHECK`` > ``EMPTINESS_CHECK``.
    The most permissive classification wins so that adding extra
    clauses to a condition can't *create* a finding that a simpler
    version of the same guard wouldn't have produced.
    """
    # ── ``and`` / ``or``: combine sub-classifications. ──
    if isinstance(cond, BinaryOp) and cond.op.lower() in ("and", "or"):
        left = classify_comparison(cond.left, target)
        right = classify_comparison(cond.right, target)
        return _strongest(left, right)

    # ── Unary not / not(...) call: invert presence/emptiness. ──
    if isinstance(cond, UnaryOp) and cond.op == "!":
        return _invert(_classify_inner(cond.operand, target))
    if (
        isinstance(cond, Call)
        and isinstance(cond.callee, Identifier)
        and cond.callee.name.lower() == "not"
        and len(cond.args) == 1
    ):
        return _invert(_classify_inner(cond.args[0], target))

    # ── Direct comparison: classify based on op + the *other* side. ──
    if isinstance(cond, BinaryOp) and cond.op in {
        "=", "!=", "<", "<=", ">", ">=",
    }:
        if expr_eq(cond.left, target):
            other = cond.right
        elif expr_eq(cond.right, target):
            other = cond.left
        else:
            return None
        if cond.op == "=":
            return EMPTINESS_CHECK if _is_empty_marker(other) else VALUE_ENGAGEMENT
        if cond.op == "!=":
            return PRESENCE_CHECK if _is_empty_marker(other) else VALUE_ENGAGEMENT
        # <, <=, >, >= — value comparison, asserts presence implicitly.
        return VALUE_ENGAGEMENT

    # ── Bare target as the entire condition: presence/truthy check. ──
    if expr_eq(cond, target):
        return PRESENCE_CHECK

    return None


def _strongest(a: str | None, b: str | None) -> str | None:
    """Return whichever classification has the higher rank."""
    return a if _RANK[a] >= _RANK[b] else b


def _classify_inner(inner: Expr, target: Expr) -> str | None:
    """Classify the operand of a ``not(...)`` / ``!`` wrapper.

    Bare ``target`` inside negation is treated as PRESENCE_CHECK on
    the inner side; the outer ``_invert`` flips it to EMPTINESS_CHECK
    (``not(X)`` ≡ "X is missing"). Anything else is classified
    normally and then inverted.
    """
    if expr_eq(inner, target):
        return PRESENCE_CHECK
    return classify_comparison(inner, target)


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


# ── Numeric guard classification (SR041) ───────────────────────────


# Classifications for ``classify_numeric_guard``. ``KNOWN_ZERO`` and
# ``KNOWN_NONZERO`` are conclusive on a single guard frame;
# ``UNKNOWN`` means the frame *references* the divisor but the guard
# does not establish either side; ``None`` means the frame does not
# reference the divisor at all (caller should keep walking outward).
KNOWN_ZERO = "KNOWN_ZERO"
KNOWN_NONZERO = "KNOWN_NONZERO"
UNKNOWN = "UNKNOWN"


def _is_numeric_zero(e: Expr) -> bool:
    """``NumberLit`` whose value is exactly 0."""
    return isinstance(e, NumberLit) and e.value == 0


def _is_numeric_nonzero_literal(e: Expr) -> bool:
    """``NumberLit`` whose value is a non-zero number."""
    return isinstance(e, NumberLit) and e.value != 0


def _is_zero_equivalent(e: Expr) -> bool:
    """Values the language treats as zero-equivalent in numeric
    contexts: numeric ``0``, ``null``, and the empty string.
    """
    return _is_numeric_zero(e) or _is_null(e) or _is_empty_string(e)


def _is_nonzero_equivalent(e: Expr) -> bool:
    """Literals known to be non-zero / non-empty: a non-zero
    ``NumberLit`` or a non-empty ``StringLit``.
    """
    if _is_numeric_nonzero_literal(e):
        return True
    if isinstance(e, StringLit) and e.value != "":
        return True
    return False


def _flip_for_else(cls: str) -> str:
    """In an else-branch, swap KNOWN_ZERO ↔ KNOWN_NONZERO; leave
    ``UNKNOWN`` alone.
    """
    if cls == KNOWN_ZERO:
        return KNOWN_NONZERO
    if cls == KNOWN_NONZERO:
        return KNOWN_ZERO
    return UNKNOWN


def _classify_magnitude_then(op: str, n: NumberLit) -> str:
    """Classify a then-branch magnitude comparison ``Y <op> N`` where
    ``N`` is a ``NumberLit``. Returns whether the interval excludes 0.

    - ``Y >  N``: 0 excluded iff ``N >= 0``.
    - ``Y >= N``: 0 excluded iff ``N >  0``.
    - ``Y <  N``: 0 excluded iff ``N <= 0``.
    - ``Y <= N``: 0 excluded iff ``N <  0``.
    """
    v = n.value
    if op == ">":
        return KNOWN_NONZERO if v >= 0 else UNKNOWN
    if op == ">=":
        return KNOWN_NONZERO if v > 0 else UNKNOWN
    if op == "<":
        return KNOWN_NONZERO if v <= 0 else UNKNOWN
    if op == "<=":
        return KNOWN_NONZERO if v < 0 else UNKNOWN
    return UNKNOWN


# Operators that flip when the operands are swapped (``a < b`` ≡ ``b > a``).
_SWAP_OP: dict[str, str] = {
    "<": ">",
    "<=": ">=",
    ">": "<",
    ">=": "<=",
    "=": "=",
    "!=": "!=",
}


def classify_numeric_guard(cond: Expr, expr: Expr, branch: str) -> str | None:
    """Classify what the guard ``cond`` (taken in ``branch`` =
    ``"then"`` or ``"else"``) tells us about whether ``expr`` is
    zero at the guarded point.

    Returns one of ``KNOWN_ZERO``, ``KNOWN_NONZERO``, ``UNKNOWN``,
    or ``None`` (``cond`` does not mention ``expr`` at all). Used by
    SR041 (div-by-zero): the check walks ``ctx.if_stack`` from
    innermost outward and uses the first non-``None`` result.

    Cases (then-branch; for else-branch the result is flipped except
    that ``UNKNOWN`` stays ``UNKNOWN``):

    - ``! expr`` / ``not(expr)`` → ``KNOWN_ZERO`` (truthy-false ⇒ 0,
      ``null``, or ``""``).
    - bare ``expr`` (used as the entire condition) → ``KNOWN_NONZERO``
      (truthy ⇒ non-zero, non-null, non-empty).
    - ``expr = 0`` / ``expr = null`` / ``expr = ""`` → ``KNOWN_ZERO``.
    - ``expr = <non-zero literal>`` or ``expr = "<non-empty string>"``
      → ``KNOWN_NONZERO`` (value engagement; in this language a
      non-empty string in a numeric context is treated as non-zero
      and the developer is asserting the value is in use).
    - ``expr = otherVar`` → ``UNKNOWN`` (we don't know other's value).
    - ``expr != 0`` / ``expr != null`` / ``expr != ""`` →
      ``KNOWN_NONZERO``.
    - ``expr != <non-zero literal>`` → ``UNKNOWN``.
    - ``expr > N`` / ``expr >= N`` / ``expr < N`` / ``expr <= N`` with
      ``N`` a numeric literal — see ``_classify_magnitude_then``.
    - Anything else referencing ``expr`` → ``UNKNOWN``.

    The helper does not recurse into ``and`` / ``or`` combinators —
    SR041 takes a conservative stance and treats compound conditions
    as ``UNKNOWN`` when a sub-clause matches but the structure is
    boolean. Callers can refine this later if real packs need it.
    """
    # Negation: ``!expr`` (defensive — language has no ``!`` token)
    # or the built-in ``not(expr)``.
    if isinstance(cond, UnaryOp) and cond.op == "!":
        if expr_eq(cond.operand, expr):
            cls = KNOWN_ZERO
            return cls if branch == "then" else _flip_for_else(cls)
        return None
    if (
        isinstance(cond, Call)
        and isinstance(cond.callee, Identifier)
        and cond.callee.name.lower() == "not"
        and len(cond.args) == 1
    ):
        if expr_eq(cond.args[0], expr):
            cls = KNOWN_ZERO
            return cls if branch == "then" else _flip_for_else(cls)
        return None

    # Bare ``expr`` as the whole condition: truthy / presence check.
    if expr_eq(cond, expr):
        cls = KNOWN_NONZERO
        return cls if branch == "then" else _flip_for_else(cls)

    # Direct comparison: one side must be ``expr``.
    if isinstance(cond, BinaryOp) and cond.op in {
        "=", "!=", "<", "<=", ">", ">=",
    }:
        if expr_eq(cond.left, expr):
            op = cond.op
            other = cond.right
        elif expr_eq(cond.right, expr):
            # Swap so the form is always ``expr <op'> other``.
            op = _SWAP_OP[cond.op]
            other = cond.left
        else:
            return None

        if op == "=":
            if _is_zero_equivalent(other):
                cls = KNOWN_ZERO
            elif _is_nonzero_equivalent(other):
                cls = KNOWN_NONZERO
            else:
                cls = UNKNOWN
        elif op == "!=":
            if _is_zero_equivalent(other):
                cls = KNOWN_NONZERO
            elif _is_nonzero_equivalent(other):
                cls = UNKNOWN
            else:
                cls = UNKNOWN
        elif op in {">", ">=", "<", "<="}:
            if isinstance(other, NumberLit):
                cls = _classify_magnitude_then(op, other)
            else:
                cls = UNKNOWN
        else:
            cls = UNKNOWN

        return cls if branch == "then" else _flip_for_else(cls)

    return None
