"""Language-semantics checks (SR055..SR059).

These checks exercise patterns specific to the BizRule scripting
language: alias mutations on arrays, ``:=``/``?=`` confusion, case
typos, unintended record auto-create, and unused variables.
"""
from __future__ import annotations

from ..ast.nodes import (
    AssignStmt,
    Call,
    FieldAccess,
    ForCounter,
    ForeachList,
    ForeachTable,
    Identifier,
    Node,
    Script,
)
from ..engine.registry import register_check
from ..engine.visitor import Check


# ── SR059 UnusedVariableCheck ──────────────────────────────────────


@register_check(
    rule_id="SR059",
    category="lang",
    severity="info",
    description="Variable assigned but never read",
)
class UnusedVariableCheck(Check):
    """Flag any variable assigned (``x := ...`` or ``x ?= ...``) but
    never read elsewhere in the script.

    Implements SPEC §6 SR059. Catches dead-code residue from refactors,
    leftover debug variables, and typo-on-read-side mistakes
    (``total := compute(); ... return totl;`` — ``total`` looks unused
    because the read site misspelled it).

    Policy:
    - Only **bare-Identifier** assignment targets count. ``obj.F := v``,
      ``obj.F[cond] := v`` and ``arr[i] := v`` mutate external state,
      not a local variable.
    - **Counter-for** (``for X := 1 to 10 do { ... }``) and **foreach**
      loop variables are loop-introduced and are excluded from both
      the assignment set and the read set — flagging them as "unused"
      when the body genuinely doesn't reference them is too noisy for
      this codebase.
    - **Function and method names in callee position are not reads.**
    - Multiple assignments to the same name collapse onto the first
      assignment's line in the finding.
    - Severity is ``info``: the rule produces hints, not blocks.
    """

    def visit_Script(self, node: Script) -> None:
        assignments: dict[str, int] = {}
        reads: set[str] = set()
        for stmt in node.statements:
            _collect(stmt, assignments, reads)

        for name in sorted(assignments):
            if name in reads:
                continue
            self.ctx.emit(
                line=assignments[name],
                message=f"variable '{name}' assigned but never read",
            )


# ── SR059 helpers ──────────────────────────────────────────────────


def _collect(
    node: Node,
    assignments: dict[str, int],
    reads: set[str],
) -> None:
    """Walk ``node`` populating the assignment table and the read set.

    The walk is hand-rolled rather than using ``children()`` so we can
    classify each context: assignment targets are *not* reads,
    loop-control variables are *neither* assignments nor reads, and
    callee identifiers are not reads.
    """
    if isinstance(node, AssignStmt):
        target = node.target
        if isinstance(target, Identifier):
            assignments.setdefault(target.name, node.line)
        else:
            # obj.F := v / arr[i] := v / obj.F[cond] := v — the target
            # itself contains reads (e.g. ``obj`` is read to locate
            # the field). Walk it.
            _collect(target, assignments, reads)
        _collect(node.value, assignments, reads)
        return

    if isinstance(node, ForCounter):
        # ``for X := start to end do body`` — X is loop-introduced.
        # start / end / body are normal subtrees and may contain reads.
        _collect(node.start, assignments, reads)
        _collect(node.end, assignments, reads)
        _collect(node.body, assignments, reads)
        return

    if isinstance(node, ForeachList):
        # ``foreach X in iterable do body`` — X is loop-introduced.
        _collect(node.iterable, assignments, reads)
        _collect(node.body, assignments, reads)
        return

    if isinstance(node, ForeachTable):
        # ``foreach obj.TABLE do body`` — no introduced variable, but
        # ``obj.TABLE`` is itself a read of ``obj``.
        _collect(node.target, assignments, reads)
        _collect(node.body, assignments, reads)
        return

    if isinstance(node, Call):
        callee = node.callee
        if isinstance(callee, FieldAccess):
            # Method call ``obj.method(args)`` — the receiver chain is
            # read, the method name itself is not a variable.
            _collect(callee.target, assignments, reads)
        # Bare-Identifier callee (``getStatus()``): skip — function
        # names are not variables in scope.
        for arg in node.args:
            _collect(arg, assignments, reads)
        return

    if isinstance(node, Identifier):
        reads.add(node.name)
        return

    # Default: descend into all children.
    for child in node.children():
        _collect(child, assignments, reads)
