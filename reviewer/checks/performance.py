"""Performance checks (SR030..SR034)."""
from __future__ import annotations

from ..ast.nodes import Call, Identifier
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
