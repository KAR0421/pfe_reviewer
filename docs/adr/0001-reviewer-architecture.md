# ADR-0001 — Reviewer architecture: AST + visitor pipeline

**Status:** Accepted
**Date:** 2026-04-20
**Supersedes:** the flat regex-per-check design in `reviewer.py` (retained as
legacy during migration)

## Context

The initial reviewer implementation (see `reviewer.py`) is a set of
standalone `check_*` functions that each run their own regex over the raw
script text, and an orchestrator (`review_bizrule`) that calls them in
sequence. This worked for a first pass but has structural problems that
get worse with every new check:

1. **No shared model of the script.** Each check re-scans and re-derives
   the same facts. Three checks independently reimplement loop detection
   and disagree on what "inside a loop" means.
2. **Text-only analysis.** Comments are not stripped before analysis, so
   `// return;` inside a comment matches the dead-code regex. String
   literals are not stripped, so SQL verbs inside `"for all users"` trip
   loop-detection heuristics. These are real cases in real packs.
3. **Ad-hoc brace tracking.** Stacks are popped on any line equal to `}`,
   which fails on `} else {`, `});`, or trailing comments. Loop-depth
   state desyncs silently.
4. **Fragile load-bearing regex.** `check_repeated_queries` assumes the
   entire pattern of assign → concat → `getSqlData(var)` matches one
   regex. Most real multi-line queries do not match; the check is quiet
   when it should fire.
5. **Plain-string findings.** No rule id, severity, category, or
   machine-readable line number. No sorting, filtering, deduplication,
   JSON output, or Bitbucket integration is possible without rewriting
   every check.
6. **Orchestration by hand-edit.** Every new check means editing
   `review_bizrule`. No way to enable/disable a rule, change severity,
   or run a single check.

The language now has an authoritative syntax spec (`syntaxe.odt` →
`docs/scripting-grammar.md`). This makes a real parser feasible.

## Decision

Replace the flat reviewer with a pipeline:

```
Script text
    │
    ▼
┌─────────────┐
│ Tokenizer   │  understands strings, comments, :=/?=, identifiers,
│             │  keywords, operators — returns Token list with line/col
└─────────────┘
    │
    ▼
┌─────────────┐
│ Parser      │  recursive-descent over tokens, produces a real AST
│             │  rooted at Script, with line numbers on every node
└─────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│ Engine                                      │
│ ┌─────────────┐   ┌──────────────────────┐  │
│ │ Registry    │   │ Context              │  │
│ │ of Check    │──▶│ enclosing loop/try,  │  │
│ │ classes     │   │ findings sink        │  │
│ └─────────────┘   └──────────────────────┘  │
│           ▼                                 │
│    NodeVisitor walks the AST once,          │
│    dispatches to every enabled Check        │
└─────────────────────────────────────────────┘
    │
    ▼
List[Finding]   (rule_id, category, severity, line, message)
    │
    ▼
┌─────────────┐
│ Reporters   │  console (dev), JSON (CI), Bitbucket (PR) — later
└─────────────┘
```

Parsing depth: **full recursive-descent producing an AST** (rather than a
tokenizer + loose structurer, or a parser-generator grammar). Rationale: a
real AST makes every future check trivial to write, and the language is
small enough (~20 statement forms, ~10 expression forms) that a hand-rolled
parser is ~500 lines.

Migration: **side-by-side** (rather than a clean rewrite, or one-PR-per-check
with the legacy removed eagerly). Rationale: we can run both pipelines on
every real pack file and diff findings to validate each new check before
trusting it.

## Package layout

```
reviewer/
├── __init__.py
├── ast/
│   ├── __init__.py
│   ├── nodes.py          # @dataclass for every AST node
│   ├── tokens.py         # Token dataclass + TokenKind enum
│   ├── tokenizer.py      # source text → list[Token]
│   └── parser.py         # list[Token] → Script (root AST node)
├── engine/
│   ├── __init__.py
│   ├── finding.py        # Finding + Report dataclasses
│   ├── registry.py       # @register_check decorator + CHECKS list
│   ├── visitor.py        # NodeVisitor base + CheckContext
│   └── runner.py         # run_review(bizrule) → Report
├── checks/
│   ├── __init__.py       # imports every check module so decorators run
│   ├── naming.py         # SR001..SR003
│   ├── docs.py           # SR010..SR012
│   ├── logic.py          # SR020..SR022
│   ├── performance.py    # SR030..SR034
│   ├── security.py       # SR040..SR043
│   ├── dependencies.py   # SR050..SR052
│   └── lang_semantics.py # SR055..SR058
└── reporters/
    ├── __init__.py
    ├── console.py
    ├── json_reporter.py
    └── bitbucket.py      # later milestone
```

The existing `reviewer.py` is renamed to `reviewer_legacy.py` and stays
until every check has a migrated counterpart (see Migration Status in
`docs/SPEC.md`).

## Token kinds

```python
class TokenKind(Enum):
    # Literals & identifiers
    IDENT; NUMBER; STRING
    # Structural
    LBRACE; RBRACE; LPAREN; RPAREN; LBRACKET; RBRACKET
    DOT; COMMA; SEMI
    # Assignment operators
    OP_ASSIGN          # :=
    OP_COND_ASSIGN     # ?=
    # Comparison
    OP_EQ; OP_NEQ; OP_LT; OP_LE; OP_GT; OP_GE
    # Arithmetic / concat
    OP_PLUS; OP_MINUS; OP_STAR; OP_SLASH
    # Keywords
    KW_IF; KW_ELSE; KW_WHILE; KW_UNTIL; KW_DO
    KW_FOR; KW_FOREACH; KW_IN; KW_TO; KW_DOWNTO
    KW_RETURN; KW_SKIP; KW_ABORT
    KW_TRY; KW_ONERROR
    KW_AND; KW_OR
    # End marker
    EOF
```

Comments are stripped by the tokenizer (kept only in a side channel in
case a future check needs them — e.g. "commented-out code left behind").
Strings preserve their content but are a single `STRING` token; their
internal text is never pattern-matched by checks.

Identifier matching: keyword lookup is **case-insensitive** for function
names in later stages, but keywords themselves are recognized
case-insensitively at tokenization time. Variable identity (for the "same
name differing only in case" check) preserves original casing on the
token.

## AST nodes

All nodes are `@dataclass(frozen=True)`, carry `line: int` (1-based), and
expose `children()` for the visitor.

Statements:
```python
Script(statements: tuple[Stmt, ...])
Block(statements: tuple[Stmt, ...])
AssignStmt(target: Expr, op: str, value: Expr)     # op ∈ {":=", "?="}
ExprStmt(expr: Expr)                                # bare call, etc.
IfStmt(cond: Expr, then_branch: Stmt, else_branch: Stmt | None)
ForCStyle(init: Stmt | None, cond: Expr | None, step: Stmt | None, body: Stmt)
ForCounter(var: Identifier, start: Expr, direction: str, end: Expr, body: Stmt)
  # direction ∈ {"to", "downto"}
ForeachList(var: Identifier, iterable: Expr, body: Stmt)
ForeachTable(target: Expr, body: Stmt)              # foreach obj.TABLE do
WhileStmt(cond: Expr, body: Stmt)
DoWhile(body: Stmt, cond: Expr)
ReturnStmt(value: Expr | None)
SkipStmt(value: Expr | None)
AbortStmt(value: Expr | None)
TryStmt(try_block: Stmt, onerror_block: Stmt)
```

Expressions:
```python
NumberLit(value: float | int)
StringLit(value: str, quote: str)                   # quote ∈ {"\"", "'"}
Identifier(name: str)
FieldAccess(target: Expr, field: str)               # obj.FIELD
TableSelector(target: Expr, field: str,
              condition: Expr)                      # obj.FIELD[cond]
ArrayIndex(array: Expr, index: Expr)                # a[n]
Call(callee: Expr, args: tuple[Expr, ...])          # fn(...) or obj.method(...)
BinaryOp(op: str, left: Expr, right: Expr)
UnaryOp(op: str, operand: Expr)
```

Notes on the parser:
- `foreach obj.TABLE do ...` is disambiguated from `foreach v in expr do ...`
  by looking at the next token after the first identifier (a `DOT` vs
  `KW_IN`).
- `for i := 1 to 10 do` vs C-style `for (init; cond; step)` is
  disambiguated by whether the next token is `LPAREN` or `IDENT`.
- A bare expression at end of script (implicit return) is parsed as
  `ExprStmt`; the runner handles the implicit-return semantic.

## Engine

```python
@dataclass
class Finding:
    rule_id: str        # "SR###"
    category: str       # naming|docs|logic|perf|security|deps|logs|scope|lang
    severity: str       # info | warning | error
    line: int | None
    message: str
    bizrule: str        # the RULE_CODE this finding belongs to

@dataclass
class Report:
    rule_name: str
    findings: tuple[Finding, ...]
    score: int | None = None   # added later
```

### Check registry

```python
CHECKS: list[type[Check]] = []

def register_check(*, rule_id, category, severity, description):
    def decorator(cls):
        cls.RULE_ID = rule_id
        cls.CATEGORY = category
        cls.DEFAULT_SEVERITY = severity
        cls.DESCRIPTION = description
        CHECKS.append(cls)
        return cls
    return decorator
```

Importing `reviewer.checks` triggers decorator registration. `run_review`
then instantiates each check with a shared `CheckContext`, runs a single
walk of the AST, and returns the collected findings.

### CheckContext

The context object maintains the ambient state every non-trivial check
needs, so checks never recompute it:

- `enter_loop(node)` / `exit_loop(node)` — stack of enclosing loops
- `enter_try(node)` / `exit_try(node)` — stack of enclosing `try` blocks
- `in_loop() -> bool`, `current_loop() -> LoopNode | None`
- `in_try() -> bool`
- `emit(rule_id, severity, line, message)` — produces a `Finding`
- `bizrule` — the full BizRule for checks that need `comment`, `scope`,
  trigger info (e.g. SR010 missing USER_COMMENT, SR060 trigger scope)

### NodeVisitor

Standard double-dispatch pattern with `visit_<NodeName>` methods and a
`generic_visit` fallback. The runner does not subclass `NodeVisitor`
directly — it **composes** checks so each statement node is visited once
per enabled check. This keeps checks decoupled and makes it cheap to skip
disabled ones.

### Example check

```python
@register_check(
    rule_id="SR030",
    category="performance",
    severity="error",
    description="SQL query executed inside a loop",
)
class SqlInLoopCheck(Check):
    def visit_Call(self, node):
        if (
            isinstance(node.callee, Identifier)
            and node.callee.name.lower() == "getsqldata"
            and self.ctx.in_loop()
        ):
            outer = self.ctx.current_loop()
            self.ctx.emit(
                line=node.line,
                message=f"SQL query inside loop that starts at line {outer.line}",
            )
        self.generic_visit(node)
```

The corresponding legacy check is ~30 lines of regex + brace counting.
The AST version is ~10 lines, correct on comments and strings, and
reuses loop-tracking from the context.

## Error strategy

- **Tokenizer errors** (e.g. unterminated string) → raise `TokenizeError`
  with line/col. The runner catches it, emits a single synthetic
  `SR999 lang-parse-error` finding with severity `error`, and skips
  further analysis of that BizRule.
- **Parser errors** (unexpected token) → raise `ParseError` with line/col
  and expected-vs-got. Same handling.
- Individual check exceptions are caught by the runner, logged, and
  reported as `SR998 check-crash` so one bad check does not kill the
  review.

Failing soft on parse errors is important: real packs contain scripts
written against older language versions or with typos the kernel
tolerates; we should still run the other checks where possible. A later
milestone can add strict mode.

## Migration plan

See `docs/SPEC.md` → "Migration Status" for the live checklist. Process:

1. **Phase 0** — Scaffold: create the `reviewer/` package with empty
   modules, `Finding` + `Report` dataclasses, registry, runner. Rename
   `reviewer.py` → `reviewer_legacy.py`. Tests still green.
2. **Phase 1** — Tokenizer: implement + exhaustive tests on tokens
   extracted from `sample_pack.xml` and `sample_pack2.xml` scripts.
3. **Phase 2** — Parser: recursive-descent, minimum subset first
   (assignments, if, function calls, return/abort/skip, blocks).
4. **Phase 3** — Parser full: foreach (both forms), for (both forms),
   while, do..while, try/onerror.
5. **Phase 4** — Engine: CheckContext, runner, composed visitor, first
   real check (`SqlInLoopCheck` — good smoke test, exercises loop
   context).
6. **Phase 5** — Wire parallel execution in `main.py`:
   ```python
   legacy = review_legacy(br)
   new    = run_review(br)
   print_report(legacy, label="legacy")
   print_report(new,    label="new")
   ```
7. **Phase 6..N** — Migrate remaining legacy checks one at a time, each
   with tests, updating the migration table. Old and new run together
   in every dev build; CI diffs their findings on pack fixtures.
8. **Phase Final** — When the migration table is all green and diffs are
   clean on every pack fixture, delete `reviewer_legacy.py` and remove
   the parallel code in `main.py`.

## Consequences

**Positive**
- Comments and strings handled once, correctly.
- Loop/try context computed once, not per check.
- Checks become ~10 lines each; severity, category, id all declarative.
- Rule enable/disable and severity config become trivial (filter
  `CHECKS` by id / category in the runner).
- JSON output is the `Report` dataclass with `dataclasses.asdict`; no
  string parsing needed for CI / Bitbucket integration.
- The grammar is now executable documentation: the parser is the ground
  truth for "what the language accepts."

**Negative**
- ~500 lines of parser/tokenizer to write and test. Upfront cost.
- Parser errors on real packs will surface — some scripts may use
  constructs not in `syntaxe.odt`. Soft-fail strategy mitigates but
  every new construct found is a small task to add to the parser.
- Two pipelines running in parallel during migration temporarily
  doubles review time in dev (not in CI, which can toggle).

**Neutral**
- Rule IDs and the `Finding` shape are committed now; changing them
  later is a refactor across every check. Pick them well up front.
