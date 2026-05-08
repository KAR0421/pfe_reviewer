"""Static-logic checks (SR020..SR022).

Currently implements:
- SR021 dead code after ``return`` / ``abort`` / ``skip``.
"""
from __future__ import annotations

from reviewer.ast.nodes import (
    AbortStmt,
    Block,
    ReturnStmt,
    Script,
    SkipStmt,
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
