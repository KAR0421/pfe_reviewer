---
description: "Scaffold the reviewer/ AST pipeline package (tokenizer, parser, engine, first check, parallel wiring)"
agent: "agent"
---
# /scaffold-pipeline

Goal: bootstrap the AST-based reviewer pipeline described in
[`docs/adr/0001-reviewer-architecture.md`](../../docs/adr/0001-reviewer-architecture.md),
running side-by-side with `reviewer_legacy.py`, so future checks can be
migrated one at a time with `/migrate-check`.

This is a multi-step, high-surface task. Work through the phases below in
order. **After each phase, pause and run the tests** before moving on.
Do not run all phases in one turn unless the user explicitly asks.

## Preconditions (check before starting)

1. Confirm `reviewer.py` exists. If yes, rename it to `reviewer_legacy.py`
   (git mv) and update any import in `main.py` from
   `from reviewer import review_bizrule` to
   `from reviewer_legacy import review_bizrule as review_legacy`.
2. Confirm `docs/scripting-grammar.md` exists (grammar reference) and
   `docs/adr/0001-reviewer-architecture.md` exists (design).
3. Confirm there is no existing `reviewer/` package. If there is, stop
   and ask the user whether to continue.

If any precondition fails, describe what you found and ask before
proceeding.

## Phase 0 — Scaffold

Create the package skeleton with stub files and empty `__init__.py`s:

```
reviewer/
├── __init__.py
├── ast/
│   ├── __init__.py
│   ├── tokens.py
│   ├── tokenizer.py
│   ├── nodes.py
│   └── parser.py
├── engine/
│   ├── __init__.py
│   ├── finding.py
│   ├── registry.py
│   ├── visitor.py
│   └── runner.py
├── checks/
│   └── __init__.py
└── reporters/
    ├── __init__.py
    └── console.py
```

And the test scaffold:
```
tests/
├── __init__.py
├── test_tokenizer.py
├── test_parser.py
├── test_engine.py
├── test_checks_performance.py
└── fixtures/
    └── smartrules/
        └── .gitkeep
```

## Phase 1 — Tokenizer

Implement in `reviewer/ast/tokens.py` and `reviewer/ast/tokenizer.py`
per `.github/instructions/ast-pipeline.instructions.md`:

- `TokenKind` enum with every kind listed in the instructions.
- `Token = @dataclass(frozen=True)` with `kind`, `value`, `line`, `col`.
- `TokenizeError(Exception)` with `line`, `col`, `message`.
- `tokenize(source: str) -> list[Token]` — consumes whitespace and
  comments, recognizes keywords case-insensitively, handles both `"..."`
  and `'...'` string literals, distinguishes `:=` / `?=` / `=` / `!=` /
  `<=` / `>=` / `<` / `>`, terminates with an `EOF` token.

Write tests in `tests/test_tokenizer.py` for:
- Every operator and punctuation token.
- Each keyword (case-insensitive).
- Numbers (integer and decimal).
- Strings in both quote styles, including strings containing `//` and
  keyword-like contents (must not tokenize as comments or keywords).
- Comments: at end of line, as a full line, between statements.
- Line/column accuracy on a multi-line input.
- Error path: unterminated string raises `TokenizeError` at the correct
  position.

Also add 1–2 fixtures under `tests/fixtures/smartrules/` extracted from
`sample_pack.xml` / `sample_pack2.xml` (strip the XML wrapping, keep the
script body), and add a test that tokenizes each without raising.

**Pause. Run tests. Confirm all green before continuing.**

## Phase 2 — AST nodes + parser (minimal subset)

Implement `reviewer/ast/nodes.py` with every node dataclass from the ADR.
All nodes are `@dataclass(frozen=True)`, carry a 1-based `line`, and
expose `children() -> Iterable[Node]`.

Implement `reviewer/ast/parser.py` with a `Parser` class that handles
the minimum subset first:
- Assignments (`:=` and `?=`)
- Function calls as statements
- `if` / `if`-`else` (both single-statement and block bodies)
- `return` / `abort` / `skip` (with and without value)
- Blocks `{ ... }`
- Expressions: identifiers, number/string literals, field access
  (`obj.FIELD`), binary operators (`+ - * / = != < <= > >= and or`),
  function calls, parenthesized expressions.

Raise `ParseError(line, col, expected, got)` on unexpected tokens.

Tests in `tests/test_parser.py`:
- Parse a simple assignment; assert node type, target name, op, value.
- Parse an `if` with single-statement branch, then with block branch.
- Parse a function call with 0, 1, and N args.
- Parse a terminator (`return expr;`).
- Parse a small fixture script end-to-end; assert the top-level
  statement count and the first statement's line number.
- Error path: missing `;` raises `ParseError` at the expected position.

**Pause. Run tests.**

## Phase 3 — Parser (remaining grammar)

Extend the parser to cover:
- `foreach X in Y do ...` AND `foreach obj.TABLE do ...` (disambiguate
  on next token after first identifier: `KW_IN` vs `DOT`).
- `for (init; cond; step) ...` AND `for X := n to/downto m do ...`
  (disambiguate on token after `KW_FOR`: `LPAREN` vs `IDENT`).
- `while (cond) ...` and `do ... while (cond);`
- `try { ... } onerror { ... }` — require `onerror` immediately after.
- Row selector `obj.FIELD[condition]` and array index `a[n]`.

Extend tests accordingly, including one positive case per form and one
fixture that exercises a mix (use a trimmed real BizRule body).

**Pause. Run tests.**

## Phase 4 — Engine

Implement exactly as described in the ADR and
`ast-pipeline.instructions.md`:
- `engine/finding.py`: `Finding` and `Report` frozen dataclasses.
- `engine/registry.py`: `@register_check(...)` decorator and the
  `CHECKS: list[type[Check]]` module-level list.
- `engine/visitor.py`: `Check` base class with `visit_<NodeName>`
  dispatch and `generic_visit`, `CheckContext` with loop/try stacks
  and `emit`.
- `engine/runner.py`: `run_review(br: BizRule) -> Report` handling
  tokenize/parse errors as a synthetic `SR999` finding and individual
  check crashes as `SR998`.

Tests in `tests/test_engine.py`:
- `run_review` on a clean script returns a `Report` with empty
  `findings`.
- `run_review` on a script with a tokenize error yields exactly one
  `SR999` finding at the right line.
- A dummy check that raises inside a `visit_*` produces one `SR998`
  finding and does not prevent other checks from running.
- Enter/exit loop and try hooks keep stacks balanced on a small fixture.

**Pause. Run tests.**

## Phase 5 — First real check + parallel wiring

Pick **`SqlInLoopCheck`** (SR030) as the first check — it exercises
`CheckContext.in_loop()` and is easy to validate against the legacy
version.

Implement in `reviewer/checks/performance.py` as shown in the
instructions file. Import the module in `reviewer/checks/__init__.py`
so the decorator runs.

Wire parallel execution in `main.py`:
```python
from reviewer_legacy import review_bizrule as review_legacy
from reviewer.engine.runner import run_review

for br in bizrules:
    legacy = review_legacy(br)
    new    = run_review(br)
    _print_legacy(legacy)
    _print_new(new)
```
Implement `_print_legacy` and `_print_new` as small helpers (the new
one can live in `reviewer/reporters/console.py`).

Add a diff-test in `tests/test_checks_performance.py` that loads a
fixture known to contain SQL inside a loop and asserts both pipelines
flag the same set of line numbers.

Update `docs/SPEC.md` → "Migration Status" table: mark SR030 as
**done** with "Diff-test clean? yes" if the diff-test passes.

**Pause. Run tests and a real run on `sample_pack.xml`.**

## After scaffolding

The user is now ready to migrate remaining legacy checks one at a time
with `/migrate-check`.

Remind the user:
- The migration table in `docs/SPEC.md` is the live scoreboard; update
  it as each check moves.
- New AST-native checks (SR055–SR058, SR040–SR043, SR050) do not have
  a legacy counterpart — implement them directly in the pipeline,
  using `/new-review-check` once the pipeline-aware version of that
  prompt exists.
