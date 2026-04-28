---
name: "AST pipeline conventions"
description: "How to write tokenizer, parser, check, and reporter code in the reviewer/ package"
applyTo: "reviewer/**,tests/test_ast*.py,tests/test_engine*.py,tests/test_checks_*.py,tests/fixtures/**"
---

# AST pipeline conventions

This file governs code in the `reviewer/` package — the AST-based review
pipeline that is replacing `reviewer_legacy.py`. Full design rationale is in
[`docs/adr/0001-reviewer-architecture.md`](../../docs/adr/0001-reviewer-architecture.md);
this file captures the rules that every new piece of code should follow.

## Package layout
```
reviewer/
├── ast/
│   ├── tokens.py      Token dataclass + TokenKind enum
│   ├── tokenizer.py   source str → list[Token]
│   ├── nodes.py       frozen dataclasses for every AST node
│   └── parser.py      list[Token] → Script (root AST node)
├── engine/
│   ├── finding.py     Finding + Report dataclasses
│   ├── registry.py    @register_check decorator, CHECKS list
│   ├── visitor.py     NodeVisitor base + CheckContext
│   └── runner.py      run_review(bizrule) → Report
├── checks/            one module per category
│   ├── naming.py              SR001..SR003
│   ├── docs.py                SR010..SR012
│   ├── logic.py               SR020..SR022
│   ├── performance.py         SR030..SR034
│   ├── security.py            SR040..SR043
│   ├── dependencies.py        SR050..SR052
│   └── lang_semantics.py      SR055..SR058
└── reporters/
    ├── console.py
    └── json_reporter.py
```

Each check lives in the module matching its category. New categories get a
new module — do not cram unrelated checks together.

## Tokenizer rules

- Input: `source: str`. Output: `list[Token]` ending in a synthetic `EOF`.
- Every token carries `kind: TokenKind`, `value: str`, `line: int`,
  `col: int`. Line and column are 1-based.
- Comments (`// ...\n`) are **consumed and discarded** during tokenization.
  Never produce `COMMENT` tokens into the main stream.
- Strings (`"..."` and `'...'`) are single `STRING` tokens. Their internal
  text is never re-tokenized, never pattern-matched by checks.
- Keyword recognition is **case-insensitive** (per spec: function names
  and control-flow keywords are case-insensitive). Identifiers preserve
  their original casing in `Token.value`.
- Raise `TokenizeError(line, col, message)` on unterminated strings or
  unrecognized characters — do not return a partial stream silently.

### Expected TokenKinds (from the ADR)
Literals: `IDENT`, `NUMBER`, `STRING`.
Structural: `LBRACE`, `RBRACE`, `LPAREN`, `RPAREN`, `LBRACKET`, `RBRACKET`,
`DOT`, `COMMA`, `SEMI`.
Assignment: `OP_ASSIGN` (`:=`), `OP_COND_ASSIGN` (`?=`).
Comparison: `OP_EQ`, `OP_NEQ`, `OP_LT`, `OP_LE`, `OP_GT`, `OP_GE`.
Arithmetic: `OP_PLUS`, `OP_MINUS`, `OP_STAR`, `OP_SLASH`.
Keywords: `KW_IF`, `KW_ELSE`, `KW_WHILE`, `KW_UNTIL`, `KW_DO`, `KW_FOR`,
`KW_FOREACH`, `KW_IN`, `KW_TO`, `KW_DOWNTO`, `KW_RETURN`, `KW_SKIP`,
`KW_ABORT`, `KW_TRY`, `KW_ONERROR`, `KW_AND`, `KW_OR`.
End: `EOF`.

## Parser rules

- Recursive-descent. One class `Parser` with a `tokens` cursor and
  `peek()` / `advance()` / `expect(kind)` helpers.
- Top-level: `parse_script() -> Script`, which parses a sequence of
  statements until `EOF`.
- Every constructed AST node carries the `line` of the first token that
  produced it. Tests must assert line numbers.
- On unexpected tokens, raise `ParseError(line, col, expected, got)`.
  Do not recover silently — the runner wraps parse errors into a single
  `SR999` finding.
- Disambiguation rules:
  - `foreach X in Y do ...` vs `foreach obj.TABLE do ...` — decided by
    whether the token after the first identifier is `KW_IN` or `DOT`.
  - `for (init; cond; step) ...` vs `for X := n to m do ...` — decided
    by whether the token after `KW_FOR` is `LPAREN` or `IDENT`.

### AST node list
See `nodes.py` and the ADR. All nodes:
```python
@dataclass(frozen=True)
class NodeName:
    ...
    line: int           # always last field so subclasses can provide default

    def children(self) -> Iterable["Node"]: ...
```
`children()` yields every child node in source order. The visitor uses it
for `generic_visit`.

## Engine rules

### `Finding` and `Report`
Exactly the dataclasses in the ADR. Do not add fields without updating the
ADR and every reporter.

### Registry
```python
@register_check(
    rule_id="SR030",
    category="performance",
    severity="error",
    description="SQL query executed inside a loop",
)
class SqlInLoopCheck(Check):
    ...
```
The decorator stores the check class in `CHECKS` in registration order.
`reviewer.checks.__init__` imports every check module so decorators run.
**Never mutate `CHECKS` at runtime** — to disable a check, filter in the
runner.

### `Check` and `CheckContext`
```python
class Check:
    RULE_ID: str
    CATEGORY: str
    DEFAULT_SEVERITY: str
    DESCRIPTION: str
    def __init__(self, ctx: "CheckContext"): self.ctx = ctx
    # visit_<NodeName> methods as needed; fall through to generic_visit
```
The context exposes:
- `enter_loop(node)` / `exit_loop(node)` — maintained by the runner as
  it descends.
- `enter_try(node)` / `exit_try(node)` — same for try/onerror.
- `in_loop() -> bool`, `current_loop() -> LoopNode | None`,
  `outer_loop() -> LoopNode | None`.
- `in_try() -> bool`.
- `emit(line, message, severity=None)` — builds a `Finding` with the
  check's `RULE_ID`, `CATEGORY`, and default severity unless overridden.
- `bizrule` — the full `BizRule` (for checks that need `comment`,
  `scope`, or trigger info).

Checks never track enclosing-loop or enclosing-try state themselves. If a
check needs structural context that the runner does not yet provide, add
it to `CheckContext` once and reuse it everywhere.

### Runner
```python
def run_review(br: BizRule) -> Report:
    try:
        tokens = tokenize(br.script)
        tree   = Parser(tokens).parse_script()
    except (TokenizeError, ParseError) as e:
        return Report(
            rule_name=br.name,
            findings=(Finding(
                rule_id="SR999", category="lang", severity="error",
                line=e.line, message=f"Parse error: {e.message}",
                bizrule=br.name,
            ),),
        )
    ctx = CheckContext(bizrule=br)
    checks = [cls(ctx) for cls in CHECKS]
    _walk(tree, ctx, checks)
    return Report(rule_name=br.name, findings=tuple(ctx.findings))
```
`_walk` is the composed visitor: for every node, it calls the context's
`enter_*` hook if applicable, dispatches `visit_<NodeName>` on every
check (swallowing individual check exceptions into an `SR998` finding),
then recurses, then calls the matching `exit_*`.

## Checks — how to write one

```python
# reviewer/checks/performance.py
from reviewer.engine.registry import register_check
from reviewer.engine.visitor import Check
from reviewer.ast.nodes import Call, Identifier

@register_check(
    rule_id="SR030",
    category="performance",
    severity="error",
    description="SQL query executed inside a loop",
)
class SqlInLoopCheck(Check):
    """Flag getSqlData(...) calls that execute inside any loop construct."""

    def visit_Call(self, node: Call) -> None:
        if (
            isinstance(node.callee, Identifier)
            and node.callee.name.lower() == "getsqldata"
            and self.ctx.in_loop()
        ):
            outer = self.ctx.current_loop()
            self.ctx.emit(
                line=node.line,
                message=(
                    f"SQL query inside loop (outer loop at line {outer.line})"
                ),
            )
```

Rules for new checks:
- **One check class per rule_id.** If one rule needs multiple AST
  patterns, handle them all in the same class with multiple `visit_*`
  methods.
- **Docstring explains WHY**, citing the SPEC row this implements.
- **Read-only visits only.** Checks never mutate the AST.
- **No regex on script text.** If you reach for `re`, stop — the fact
  you need is either on a node or belongs in `CheckContext`.
- **Line number always from a node** (`node.line` or
  `node.callee.line`). Never compute line numbers by scanning text.
- **Every check has tests.** See below.

## Tests

Tests live under `tests/`. Layout:
```
tests/
├── test_tokenizer.py
├── test_parser.py
├── test_engine.py
├── test_checks_performance.py
├── test_checks_docs.py
├── ...
└── fixtures/
    ├── smartrules/
    │   ├── sql_in_foreach.smartrule
    │   ├── nested_loops.smartrule
    │   └── clean_simple.smartrule
    └── packs/
        └── minimal_pack.xml
```

### What each fixture is
- `.smartrule` — plain text of a single `IMPACT` body (not wrapped in XML).
  Mirror the style of real scripts from `sample_pack.xml`: `:=` / `?=`,
  `foreach … in … do { … }`, string-concatenated SQL, French/English
  comments.

### What every check must have
1. **Positive** — a fixture where the issue is present; assert exactly
   the set of expected findings (rule_id, line, key message substring).
2. **Negative** — a fixture where the issue is absent; assert that the
   check produced zero findings.
3. **Edge** — at least one of: empty script, comments-only script,
   issue-shaped pattern inside a comment, issue-shaped pattern inside a
   string literal, minified on one line. The AST pipeline must handle
   these correctly by construction; tests prove it.

### Diff-test during migration
For each migrated check, add a parametrized test that loads every
`.smartrule` fixture and asserts that the AST check and its legacy
counterpart return findings that cover the same line numbers. Findings
may differ in wording — they must agree on *where* issues are.

## Reporters

- `console.py` — pretty-prints a `Report` for humans.
- `json_reporter.py` — `dataclasses.asdict` then `json.dumps`.
- `bitbucket.py` — **later milestone, do not implement yet.**

Reporters consume `Report` — they never touch the AST or the
tokenizer. Keep this boundary sharp.

## Things this package must NOT do
- Import from `reviewer_legacy`. The legacy module is quarantined; the
  AST pipeline is a fresh build.
- Regex over raw script text inside any check.
- Track enclosing-loop/try state inside checks (use `CheckContext`).
- Mutate `CHECKS` at runtime (filter, don't mutate).
- Silently swallow parse errors (route through `SR999`).
- Silently swallow check exceptions (route through `SR998`).
