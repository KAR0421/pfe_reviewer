"""Run a full review on a single BizRule.

The runner:

1. Tokenizes and parses the script. On failure, returns a single
   synthetic ``SR999`` finding and skips further analysis.
2. Walks the AST once, dispatching every node to every registered
   check. Per-check exceptions are isolated as ``SR998`` findings so a
   single broken check does not abort the review.
3. Maintains the loop and try stacks on the shared ``CheckContext`` so
   checks never have to recompute that state.
"""
from __future__ import annotations

from ..ast.nodes import Node, TryStmt
from ..ast.parser import ParseError, Parser
from ..ast.tokenizer import TokenizeError, tokenize
from .finding import Finding, Report
from .registry import CHECKS
from .visitor import LOOP_TYPES, Check, CheckContext

# Eagerly import the check modules so their decorators register them.
from .. import checks  # noqa: F401  (registers checks on import)


def run_review(br) -> Report:
    """Tokenize, parse, and walk a BizRule, returning a Report."""
    try:
        tokens = tokenize(br.script)
        tree = Parser(tokens).parse_script()
    except (TokenizeError, ParseError) as e:
        return Report(
            rule_name=br.name,
            findings=(
                Finding(
                    rule_id="SR999",
                    category="lang",
                    severity="error",
                    line=getattr(e, "line", None),
                    message=f"Parse error: {e.message}",
                    bizrule=br.name,
                ),
            ),
        )

    ctx = CheckContext(bizrule=br)
    check_instances: list[Check] = [cls(ctx) for cls in CHECKS]
    _walk(tree, ctx, check_instances)
    return Report(rule_name=br.name, findings=tuple(ctx.findings))


def _walk(node: Node, ctx: CheckContext, checks: list[Check]) -> None:
    """Visit ``node`` with every check, then recurse into its children.

    Maintains loop/try stacks on entry and exit. Each check's exception
    is caught and reported as ``SR998 check-crash``.
    """
    is_loop = isinstance(node, LOOP_TYPES)
    is_try = isinstance(node, TryStmt)
    if is_loop:
        ctx.enter_loop(node)
    if is_try:
        ctx.enter_try(node)

    for check in checks:
        ctx._current_check = check
        try:
            check.visit(node)
        except Exception as exc:  # noqa: BLE001 - isolate broken checks
            ctx.findings.append(
                Finding(
                    rule_id="SR998",
                    category="lang",
                    severity="error",
                    line=getattr(node, "line", None),
                    message=(
                        f"Check {type(check).__name__} crashed on "
                        f"{type(node).__name__}: {exc!r}"
                    ),
                    bizrule=ctx.bizrule.name,
                )
            )
    ctx._current_check = None

    for child in node.children():
        _walk(child, ctx, checks)

    if is_try:
        ctx.exit_try(node)
    if is_loop:
        ctx.exit_loop(node)
