"""Log-quality checks (SR090..SR092).

Currently implements:
- SR090 verbose log call inside a loop.
- SR091 long script with insufficient log density relative to
  branching / loop / risky-call complexity.

Both checks use the runner's loop stack and walk the parsed AST, so
loop keywords inside comments/strings, post-loop logs, and per-call
attribution all behave correctly by construction.
"""
from __future__ import annotations

from ..ast.nodes import (
    Block,
    Call,
    DoWhile,
    FieldAccess,
    ForCStyle,
    ForCounter,
    ForeachList,
    ForeachTable,
    Identifier,
    IfStmt,
    Node,
    Script,
    Stmt,
    TryStmt,
    WhileStmt,
)
from ..engine.registry import register_check
from ..engine.visitor import Check


# Verbose-log built-ins. Lower-cased so we match case-insensitively
# without mutating the AST. Shared by SR090 and SR091 so the two
# checks always agree on what counts as "a log".
_LOG_NAMES: frozenset[str] = frozenset({"msginfo", "msgerror", "msgwarn"})


def _is_log_call(node: Node) -> bool:
    """True iff ``node`` is a call to one of the verbose-log built-ins.

    Only a bare ``Identifier`` callee is treated as a log — method-style
    forms like ``obj.msginfo(...)`` aren't built-ins, so they don't
    count (and don't behave like the global logger anyway).
    """
    if not isinstance(node, Call):
        return False
    callee = node.callee
    return isinstance(callee, Identifier) and callee.name.lower() in _LOG_NAMES


# ── SR090 VerboseLogInLoopCheck ────────────────────────────────────


@register_check(
    rule_id="SR090",
    category="logs",
    severity="warning",
    description="Verbose log call inside a loop.",
)
class VerboseLogInLoopCheck(Check):
    """Flag every ``msginfo`` / ``msgerror`` / ``msgwarn`` call site
    that is lexically inside a loop body.

    Implements SPEC §8 SR090. The check asks the runner's loop stack
    via ``ctx.in_loop()`` — comments and strings have already been
    discarded by the tokenizer, the loop stack pops correctly when the
    body's ``Block`` ends, and *every* matching call site is reported.
    """

    def visit_Call(self, node: Call) -> None:
        if not self.ctx.in_loop():
            return
        if not _is_log_call(node):
            return
        outer = self.ctx.current_loop()
        # ``outer`` is None only if ``in_loop()`` lied; defensive check.
        outer_line = outer.line if outer is not None else node.line
        self.ctx.emit(
            line=node.line,
            message=(
                f"Verbose log call '{node.callee.name}' inside loop "
                f"(loop header at line {outer_line})"
            ),
        )


# ── SR091 TooFewLogsCheck ──────────────────────────────────────────


# A long script is anything past this many statements; below it, no
# amount of complexity warrants requiring logs (the script is short
# enough to read top-to-bottom).
_LONG_SCRIPT_THRESHOLD: int = 50

# One log call per N units of "complexity" (branches + loops + risky
# calls). Conservative: most well-structured scripts pass; only the
# genuinely under-instrumented ones trip. See SPEC §8 SR091 footnote.
_LOG_DENSITY_RATIO: int = 5

# Loop node types — anything iterative counts as one unit of
# complexity. Mirrors LOOP_TYPES in the visitor module but is kept
# local so this file's intent is self-contained.
_LOOP_TYPES: tuple[type, ...] = (
    ForCStyle, ForCounter, ForeachList, ForeachTable, WhileStmt, DoWhile,
)

# "Risky" built-ins: things that talk to the database, an external
# service, or fetch live objects. A failure inside one of these is the
# kind of thing you can only diagnose from logs in production.
_RISKY_EXACT_NAMES: frozenset[str] = frozenset({"getsqldata", "callservice"})
_RISKY_PREFIXES: tuple[str, ...] = ("getobject",)


def _is_risky_call(node: Node) -> bool:
    """True iff ``node`` is a call to a built-in we'd want logged.

    Two callee shapes are recognised:

    - Bare ``Identifier`` (``getSqlData(...)``, ``callService(...)``,
      ``getObject(...)``, ``getObjectByX(...)``) — the global
      built-ins.
    - ``FieldAccess`` whose field is ``getobject*`` or ``callservice``
      (``obj.getObject(reportId)``, ``obj.getObjects(...)``) — these
      do exist on objects in this language. ``obj.getSqlData(...)``
      does not exist, so SQL is intentionally only matched on the
      bare-identifier branch.
    """
    if not isinstance(node, Call):
        return False
    callee = node.callee
    if isinstance(callee, Identifier):
        name = callee.name.lower()
        if name in _RISKY_EXACT_NAMES:
            return True
        return any(name.startswith(p) for p in _RISKY_PREFIXES)
    if isinstance(callee, FieldAccess):
        name = callee.field.lower()
        if name == "callservice":
            return True
        return any(name.startswith(p) for p in _RISKY_PREFIXES)
    return False


def _count_statements(node: Node) -> int:
    """Count ``Stmt`` subclass nodes in ``node``'s subtree, excluding
    container statements (``Block``) so the count reflects real work,
    not nesting depth.
    """
    total = 0
    if isinstance(node, Stmt) and not isinstance(node, Block):
        total += 1
    for child in node.children():
        total += _count_statements(child)
    return total


def _count_log_calls(node: Node) -> int:
    """Count call sites in ``node``'s subtree that look like a log."""
    total = 1 if _is_log_call(node) else 0
    for child in node.children():
        total += _count_log_calls(child)
    return total


def _count_complexity(node: Node) -> int:
    """Count branches + loops + risky calls in ``node``'s subtree.

    These are the constructs whose runtime behaviour you'd reach for
    logs to explain. A script with many of them but no logs is
    unobservable in production — that's exactly what SR091 catches.
    """
    total = 0
    if isinstance(node, IfStmt):
        total += 1
    if isinstance(node, _LOOP_TYPES):
        total += 1
    if _is_risky_call(node):
        total += 1
    for child in node.children():
        total += _count_complexity(child)
    return total


@register_check(
    rule_id="SR091",
    category="logs",
    severity="info",
    description=(
        "Long script with insufficient log density relative to its "
        "branching / loop / risky-call complexity."
    ),
)
class TooFewLogsCheck(Check):
    """Flag long scripts whose log density is too low to debug them in
    production.

    Implements SPEC §8 SR091. The rule is framed around
    **observability**: we flag a script when:

    - it has more than ``_LONG_SCRIPT_THRESHOLD`` statements
      (anything shorter is small enough to read), AND
    - it has fewer log calls than ``complexity / _LOG_DENSITY_RATIO``,
      where ``complexity`` is the number of branches, loops, and
      risky calls (SQL / service / live-object lookups).

    A script with high complexity must justify itself with at least one
    log per ``_LOG_DENSITY_RATIO`` complex constructs. A long but
    straight-line script with no complexity is *not* flagged — there
    is nothing to diagnose, so logs aren't needed.
    """

    def visit_Script(self, node: Script) -> None:
        stmts = _count_statements(node)
        if stmts <= _LONG_SCRIPT_THRESHOLD:
            return
        logs = _count_log_calls(node)
        complexity = _count_complexity(node)
        # Strict ``<``: equality with the ratio passes, so a script
        # with complexity == _LOG_DENSITY_RATIO and logs == 1 is fine.
        if logs * _LOG_DENSITY_RATIO >= complexity:
            return
        self.ctx.emit(
            line=1,
            message=(
                f"Long script ({stmts} statements) with insufficient "
                f"diagnostics: {logs} log call(s) but {complexity} "
                f"branches/loops/risky calls. Production failures "
                f"will be hard to trace."
            ),
        )


# ── SR093 EmptyOnerrorBlockCheck ───────────────────────────────────


@register_check(
    rule_id="SR093",
    category="logs",
    severity="error",
    description="Empty onerror block swallows errors silently",
)
class EmptyOnerrorBlockCheck(Check):
    """Flag any ``try { ... } onerror { }`` whose ``onerror`` body is
    a literally empty block.

    Implements SPEC §6 SR093. An empty ``onerror`` block is the worst
    possible error path: a real failure produces no log, no abort, no
    signal at all — the only way to discover something went wrong is
    downstream data corruption.

    Scope is intentionally narrow:
    - fire only when ``onerror_block`` is a ``Block`` with zero
      statements;
    - non-empty blocks (even ones that "do nothing useful" like a
      single bare assignment) are SR094's territory, not this rule's;
    - comments are dropped by the tokenizer before parsing, so an
      ``onerror { /* TODO */ }`` is, structurally, ``onerror { }``
      and is correctly flagged here.
    """

    def visit_TryStmt(self, node: TryStmt) -> None:
        body = node.onerror_block
        if isinstance(body, Block) and len(body.statements) == 0:
            self.ctx.emit(
                line=node.line,
                message=(
                    f"Empty onerror block at line {node.line}: errors "
                    "will be silently swallowed."
                ),
            )


# ── SR094 OnerrorWithoutErrorHandlingCheck ─────────────────────────


def _references_error_object(root: Node) -> bool:
    """True iff any ``FieldAccess`` whose target is an ``Identifier``
    named ``error`` (case-insensitively) lives anywhere in ``root``.

    That covers ``error.consume``, ``error.getMessage()``,
    ``x := error.code``, ``if (error.severity > 0) ...`` — every shape
    of "do something with the implicit error object".
    """
    if (
        isinstance(root, FieldAccess)
        and isinstance(root.target, Identifier)
        and root.target.name.lower() == "error"
    ):
        return True
    for child in root.children():
        if _references_error_object(child):
            return True
    return False


@register_check(
    rule_id="SR094",
    category="logs",
    severity="warning",
    description=(
        "onerror block doesn't engage with the implicit error "
        "(ScriptError) object"
    ),
)
class OnerrorWithoutErrorHandlingCheck(Check):
    """Flag a non-empty ``onerror`` block that never touches the
    implicit ``error`` (``ScriptError``) object.

    Implements SPEC §6 SR094. Real error handling means engaging the
    implicit ``error`` variable through a field access or method call
    — ``error.consume()`` marks the error handled, ``error.getMessage()``
    extracts the message, and similar members exist. Without any
    ``error.<something>`` reference the exception is neither consumed
    nor inspected, and the runtime may keep propagating it even if the
    block logs a message.

    Log calls (``msginfo`` / ``msgerror`` / ``msgwarn``) are extras
    for human visibility, not error handling: a block can log heavily
    and still fail this rule. In that case the log preserves a trace,
    but the error itself is unconsumed — hence ``warning``, not
    ``error``: visible but not consumed, not a silent black hole
    (that case is SR093).

    Coexists with SR093 on the same ``TryStmt`` by construction:
    empty block → SR093 fires and SR094 skips; non-empty block with
    no ``error.<x>`` → SR094 fires and SR093 skips; non-empty block
    that touches ``error`` → neither fires.
    """

    def visit_TryStmt(self, node: TryStmt) -> None:
        body = node.onerror_block
        # Empty / comment-only blocks are SR093's territory.
        if isinstance(body, Block) and len(body.statements) == 0:
            return
        if _references_error_object(body):
            return
        self.ctx.emit(
            line=node.line,
            message=(
                f"onerror block at line {node.line} doesn't engage "
                "with the 'error' object: no error.<method> or "
                "error.<field> access. The exception is not consumed "
                "— even if logged, the runtime may keep propagating it."
            ),
        )
