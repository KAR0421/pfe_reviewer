"""Helpers for checks that reason about field-access patterns.

Currently used by SR034 (repeated field reads). The structural-identity
helper is module-level so future checks (e.g. SR042 null-guarded field
access) can share the same notion of "the same field on the same object".
"""
from __future__ import annotations

from ..ast.nodes import Expr, FieldAccess, Identifier


def dotted_name(expr: Expr) -> str | None:
    """Return a stable string identity for ``expr`` if it is either a
    bare ``Identifier`` (``"obj"``) or a chain of ``FieldAccess`` whose
    ultimate root is an identifier (``"obj.sub.deeper"``). Otherwise
    return ``None``.

    Returning ``None`` for non-bare-rooted expressions is deliberate:
    forms like ``getThing().F`` have no stable source we can use as a
    cache-invalidation key, so any check that needs structural identity
    for caching/aliasing analysis should skip those expressions rather
    than guess.
    """
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, FieldAccess):
        base = dotted_name(expr.target)
        if base is None:
            return None
        return f"{base}.{expr.field}"
    return None


def field_key(fa: FieldAccess) -> tuple[str, str] | None:
    """Return ``(target_dotted, field)`` if ``fa.target`` has a stable
    dotted name, else ``None``.

    The two-tuple form is the structural-identity key SR034 uses for
    its "have I seen this read before?" map; SR042 will likely reuse it
    when it lands in M2.
    """
    base = dotted_name(fa.target)
    if base is None:
        return None
    return (base, fa.field)


def root_var(dotted: str) -> str:
    """Leftmost name in a dotted path. ``"obj.sub.F"`` → ``"obj"``.

    SR034 uses this to decide whether a plain-variable reassignment
    (``obj := getOther()``) invalidates a cached read of any field
    rooted at that variable.
    """
    return dotted.split(".", 1)[0]
