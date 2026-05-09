"""SQL helpers for SR032 (RepeatedQueryCheck).

Lives in its own module so the check can stay focused on policy and the
parsing details remain testable in isolation.

The pipeline is:
    raw AST argument → flattened SQL string → ParsedQuery
                                             ↑
                                       sqlparse-driven
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Where

from ..ast.nodes import (
    AssignStmt,
    BinaryOp,
    Identifier,
    Node,
    StringLit,
)


# A normalized WHERE conjunct. ``column`` is lowercased; ``op`` is the
# raw operator (``=``, ``!=``, ``<``, ``in``, ``like`` …); ``value`` is
# the right-hand-side string with whitespace collapsed and casing
# preserved (literals are case-significant in Oracle string compares).
@dataclass(frozen=True)
class Conjunct:
    column: str
    op: str
    value: str


@dataclass(frozen=True)
class ParsedQuery:
    """Structured view of a flattened ``SELECT`` statement."""

    select_fields: frozenset[str]
    table: str
    where_conjuncts: tuple[Conjunct, ...]


# ── AST → SQL string flattening ────────────────────────────────────


def collect_string_assignments(root: Node) -> dict[str, list[Node]]:
    """Walk ``root`` and collect every ``name := <expr>`` assignment
    whose right-hand side is a string-flattenable expression (a
    ``StringLit`` or a tree of ``+`` concatenations).

    The result lets us substitute simple ``getSqlData(varName)`` call
    sites where the SQL was assembled into ``varName`` once. We only
    substitute when **exactly one** assignment exists for the name —
    multiple assignments mean the value is ambiguous.
    """
    out: dict[str, list[Node]] = {}
    for assign in _walk_kind(root, AssignStmt):
        if assign.op != ":=":
            continue
        target = assign.target
        if not isinstance(target, Identifier):
            continue
        if not _is_string_flattenable(assign.value):
            continue
        out.setdefault(target.name, []).append(assign.value)
    return out


def flatten_query_arg(
    expr: Node,
    string_assignments: dict[str, list[Node]],
) -> str:
    """Flatten an SQL-building expression to a single string.

    - ``StringLit`` contributes its raw text verbatim.
    - ``BinaryOp(+)`` is concatenation; recurse on both sides.
    - ``Identifier`` is substituted from ``string_assignments`` if
      exactly one assignment is known; otherwise it becomes ``?``.
    - Anything else is a runtime expression — replaced by ``?``.
    """
    return _flatten(expr, string_assignments, _seen=set())


def _flatten(expr: Node, assigns: dict[str, list[Node]], _seen: set[str]) -> str:
    if isinstance(expr, StringLit):
        return expr.value
    if isinstance(expr, BinaryOp) and expr.op == "+":
        return _flatten(expr.left, assigns, _seen) + _flatten(
            expr.right, assigns, _seen
        )
    if isinstance(expr, Identifier):
        candidates = assigns.get(expr.name, [])
        if len(candidates) == 1 and expr.name not in _seen:
            # Guard against self-referential cycles (``x := x + " more"``).
            return _flatten(candidates[0], assigns, _seen | {expr.name})
        return "?"
    return "?"


def _is_string_flattenable(expr: Node) -> bool:
    if isinstance(expr, StringLit):
        return True
    if isinstance(expr, BinaryOp) and expr.op == "+":
        return _is_string_flattenable(expr.left) or _is_string_flattenable(
            expr.right
        )
    return False


def _walk_kind(root: Node, kind: type) -> Iterable[Node]:
    if isinstance(root, kind):
        yield root
    for child in root.children():
        yield from _walk_kind(child, kind)


# ── SQL string → ParsedQuery ───────────────────────────────────────


_SELECT_RE = re.compile(
    r"^\s*SELECT\s+(?P<fields>.+?)\s+FROM\s+(?P<table>[A-Za-z0-9_.\"]+)"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+(?:ORDER\s+BY|GROUP\s+BY|HAVING|FETCH|FOR\s+UPDATE)\b.*)?\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def parse_query(raw_sql: str) -> ParsedQuery | None:
    """Parse a flattened SQL string into a ``ParsedQuery``.

    Returns ``None`` if the string is not a recognizable single
    ``SELECT`` — covers DML (``INSERT``/``UPDATE``/``DELETE``),
    multi-statement strings, free-form text, and SELECTs whose shape
    falls outside the ``_SELECT_RE`` grammar (e.g. subqueries in the
    ``FROM`` clause).

    **Contract**: callers (notably ``RepeatedQueryCheck``) must treat
    a ``None`` result as "skip this call site silently". Unparseable
    queries are deliberately not paired with anything — a false
    positive on garbage would be more annoying than missing a
    duplicate inside genuinely malformed code. This function never
    raises on ill-formed input.

    We use ``sqlparse`` only to normalize whitespace and uppercase
    keywords; this gives us a stable string for the structural regex
    below *without* hand-writing a SQL tokenizer for the language we
    already proxy through ``sqlparse``.
    """
    if not raw_sql or not raw_sql.strip():
        return None

    formatted = sqlparse.format(
        raw_sql,
        keyword_case="upper",
        strip_comments=True,
        reindent=False,
    )
    # Collapse all runs of whitespace to a single space.
    flat = re.sub(r"\s+", " ", formatted).strip()
    if not flat.upper().lstrip().startswith("SELECT"):
        return None

    m = _SELECT_RE.match(flat)
    if m is None:
        return None

    fields_raw = m.group("fields")
    table_raw = m.group("table")
    where_raw = m.group("where") or ""

    select_fields = frozenset(
        f.strip().lower() for f in _split_top_level(fields_raw, ",") if f.strip()
    )
    table = table_raw.strip().lower().strip('"')

    where_conjuncts = _parse_where(where_raw)

    return ParsedQuery(
        select_fields=select_fields,
        table=table,
        where_conjuncts=where_conjuncts,
    )


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split ``s`` on ``sep`` at parenthesis depth 0."""
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


_AND_SPLIT_RE = re.compile(r"\s+AND\s+", re.IGNORECASE)
_CONJUNCT_RE = re.compile(
    r"^\s*(?P<col>[A-Za-z_][A-Za-z0-9_.]*)\s*"
    r"(?P<op>!=|<>|<=|>=|=|<|>|LIKE|NOT\s+LIKE|IN|NOT\s+IN)\s*"
    r"(?P<val>.+?)\s*$",
    re.IGNORECASE,
)


def _parse_where(where_raw: str) -> tuple[Conjunct, ...]:
    if not where_raw.strip():
        return ()
    parts = _AND_SPLIT_RE.split(where_raw)
    out: list[Conjunct] = []
    for part in parts:
        m = _CONJUNCT_RE.match(part)
        if m is None:
            # Unparseable conjunct — treat as opaque so two queries
            # with the same opaque text still match.
            out.append(Conjunct(column="?", op="?", value=part.strip().lower()))
            continue
        col = m.group("col").lower()
        op = re.sub(r"\s+", " ", m.group("op")).upper()
        val = m.group("val").strip()
        out.append(Conjunct(column=col, op=op, value=val))
    # Order-independent: sort so ``a=1 AND b=2`` matches ``b=2 AND a=1``.
    return tuple(sorted(out, key=lambda c: (c.column, c.op, c.value)))


# ── sqlparse-aware single-call extraction (kept for future use) ────


def find_where_block(stmt: sqlparse.sql.Statement) -> Where | None:
    for tok in stmt.tokens:
        if isinstance(tok, Where):
            return tok
    return None


__all__ = [
    "Conjunct",
    "ParsedQuery",
    "collect_string_assignments",
    "flatten_query_arg",
    "parse_query",
    "find_where_block",
]
