"""Check base class and CheckContext.

Checks subclass ``Check`` and define ``visit_<NodeName>`` methods. They
never track enclosing-loop or enclosing-try state themselves — the
runner maintains those stacks on the shared ``CheckContext``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ..ast.nodes import (
    DoWhile,
    ForCStyle,
    ForCounter,
    ForeachList,
    ForeachTable,
    Node,
    TryStmt,
    WhileStmt,
)
from .finding import Finding

if TYPE_CHECKING:  # pragma: no cover
    from parser import BizRule  # noqa: F401  (only for hint)


# Loop node tuple for isinstance checks in the runner.
LOOP_TYPES: tuple[type, ...] = (
    ForCStyle, ForCounter, ForeachList, ForeachTable, WhileStmt, DoWhile,
)


class CheckContext:
    """Ambient state shared by every check during a single review."""

    def __init__(self, bizrule) -> None:
        self.bizrule = bizrule
        self._loop_stack: list[Node] = []
        self._try_stack: list[TryStmt] = []
        self.findings: list[Finding] = []
        # Set by the runner before dispatching each check.
        self._current_check: "Check | None" = None

    # ── Loop stack ────────────────────────────────────────────────

    def enter_loop(self, node: Node) -> None:
        self._loop_stack.append(node)

    def exit_loop(self, node: Node) -> None:
        # Defensive pop in case of imbalanced calls.
        if self._loop_stack and self._loop_stack[-1] is node:
            self._loop_stack.pop()

    def in_loop(self) -> bool:
        return bool(self._loop_stack)

    def current_loop(self) -> Node | None:
        return self._loop_stack[-1] if self._loop_stack else None

    def outer_loop(self) -> Node | None:
        if len(self._loop_stack) >= 2:
            return self._loop_stack[-2]
        return None

    # ── Try stack ─────────────────────────────────────────────────

    def enter_try(self, node: TryStmt) -> None:
        self._try_stack.append(node)

    def exit_try(self, node: TryStmt) -> None:
        if self._try_stack and self._try_stack[-1] is node:
            self._try_stack.pop()

    def in_try(self) -> bool:
        return bool(self._try_stack)

    # ── Emission ─────────────────────────────────────────────────

    def emit(
        self,
        line: int | None,
        message: str,
        severity: str | None = None,
    ) -> None:
        check = self._current_check
        if check is None:  # pragma: no cover - runner always sets this
            raise RuntimeError("CheckContext.emit() called outside a check dispatch")
        self.findings.append(
            Finding(
                rule_id=check.RULE_ID,
                category=check.CATEGORY,
                severity=severity or check.DEFAULT_SEVERITY,
                line=line,
                message=message,
                bizrule=self.bizrule.name,
            )
        )


class Check:
    """Base class for all checks.

    Subclasses set their metadata via ``@register_check`` and define
    ``visit_<NodeName>`` methods as needed. Unhandled nodes fall through
    to ``generic_visit`` (a no-op by default; child traversal is the
    runner's job).
    """

    RULE_ID: ClassVar[str] = ""
    CATEGORY: ClassVar[str] = ""
    DEFAULT_SEVERITY: ClassVar[str] = "warning"
    DESCRIPTION: ClassVar[str] = ""

    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx

    def visit(self, node: Node) -> None:
        """Dispatch ``node`` to ``visit_<NodeName>`` if defined."""
        method_name = f"visit_{type(node).__name__}"
        method = getattr(self, method_name, None)
        if method is not None:
            method(node)
        else:
            self.generic_visit(node)

    def generic_visit(self, node: Node) -> None:  # noqa: D401
        """No-op fallback. The runner handles child traversal."""
        return None
