"""AST node dataclasses for the BizRule scripting language.

Every node is frozen, carries a 1-based ``line`` of the first token that
produced it, and exposes ``children()`` so the engine's visitor can walk
the tree generically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Union


# ── Base ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Node:
    """Common base; subclasses always define their own ``line``."""

    def children(self) -> Iterable["Node"]:
        return ()


# ── Expressions ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Expr(Node):
    pass


@dataclass(frozen=True)
class NumberLit(Expr):
    value: float
    raw: str
    line: int = 0


@dataclass(frozen=True)
class StringLit(Expr):
    value: str
    quote: str  # '"' or "'"
    line: int = 0


@dataclass(frozen=True)
class Identifier(Expr):
    name: str
    line: int = 0


@dataclass(frozen=True)
class FieldAccess(Expr):
    target: Expr
    field: str
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.target


@dataclass(frozen=True)
class TableSelector(Expr):
    """``obj.FIELD[condition]`` — row selector with a filter expression."""

    target: Expr
    field: str
    condition: "Expr"
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.target
        yield self.condition


@dataclass(frozen=True)
class ArrayIndex(Expr):
    array: Expr
    index: Expr
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.array
        yield self.index


@dataclass(frozen=True)
class Call(Expr):
    callee: Expr
    args: tuple[Expr, ...] = ()
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.callee
        yield from self.args


@dataclass(frozen=True)
class BinaryOp(Expr):
    op: str
    left: Expr
    right: Expr
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.left
        yield self.right


@dataclass(frozen=True)
class UnaryOp(Expr):
    op: str
    operand: Expr
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.operand


# ── Statements ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stmt(Node):
    pass


@dataclass(frozen=True)
class Block(Stmt):
    statements: tuple[Stmt, ...] = ()
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield from self.statements


@dataclass(frozen=True)
class AssignStmt(Stmt):
    target: Expr
    op: str  # ":=" or "?="
    value: Expr
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.target
        yield self.value


@dataclass(frozen=True)
class ExprStmt(Stmt):
    expr: Expr
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.expr


@dataclass(frozen=True)
class IfStmt(Stmt):
    cond: Expr
    then_branch: Stmt
    else_branch: Stmt | None = None
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.cond
        yield self.then_branch
        if self.else_branch is not None:
            yield self.else_branch


@dataclass(frozen=True)
class ReturnStmt(Stmt):
    value: Expr | None = None
    line: int = 0

    def children(self) -> Iterable[Node]:
        if self.value is not None:
            yield self.value


@dataclass(frozen=True)
class SkipStmt(Stmt):
    value: Expr | None = None
    line: int = 0

    def children(self) -> Iterable[Node]:
        if self.value is not None:
            yield self.value


@dataclass(frozen=True)
class AbortStmt(Stmt):
    value: Expr | None = None
    line: int = 0

    def children(self) -> Iterable[Node]:
        if self.value is not None:
            yield self.value


# ── Loops (Phase 3 will populate parsers; nodes declared up-front) ─


@dataclass(frozen=True)
class ForCStyle(Stmt):
    init: Stmt | None
    cond: Expr | None
    step: Stmt | None
    body: Stmt
    line: int = 0

    def children(self) -> Iterable[Node]:
        if self.init is not None:
            yield self.init
        if self.cond is not None:
            yield self.cond
        if self.step is not None:
            yield self.step
        yield self.body


@dataclass(frozen=True)
class ForCounter(Stmt):
    var: Identifier
    start: Expr
    direction: str  # "to" or "downto"
    end: Expr
    body: Stmt
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.var
        yield self.start
        yield self.end
        yield self.body


@dataclass(frozen=True)
class ForeachList(Stmt):
    var: Identifier
    iterable: Expr
    body: Stmt
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.var
        yield self.iterable
        yield self.body


@dataclass(frozen=True)
class ForeachTable(Stmt):
    target: Expr  # obj.TABLE
    body: Stmt
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.target
        yield self.body


@dataclass(frozen=True)
class WhileStmt(Stmt):
    cond: Expr
    body: Stmt
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.cond
        yield self.body


@dataclass(frozen=True)
class DoWhile(Stmt):
    body: Stmt
    cond: Expr
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.body
        yield self.cond


@dataclass(frozen=True)
class TryStmt(Stmt):
    try_block: Stmt
    onerror_block: Stmt
    line: int = 0

    def children(self) -> Iterable[Node]:
        yield self.try_block
        yield self.onerror_block


# ── Root ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Script(Node):
    statements: tuple[Stmt, ...] = ()
    line: int = 1

    def children(self) -> Iterable[Node]:
        yield from self.statements


# Convenience union for type hints
LoopNode = Union[ForCStyle, ForCounter, ForeachList, ForeachTable, WhileStmt, DoWhile]
