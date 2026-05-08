---
description: "Migrate a single legacy check_* function to an AST-based Check class"
agent: "agent"
---
# /migrate-check

Migrate one function from `reviewer_legacy.py` to an AST-based `Check`
class in the `reviewer/` package, following
[`.github/instructions/ast-pipeline.instructions.md`](../instructions/ast-pipeline.instructions.md)
and [`docs/adr/0001-reviewer-architecture.md`](../../docs/adr/0001-reviewer-architecture.md).

Inputs:
- Legacy function name: ${input:legacyFn:e.g. check_sql_in_loops}
- Target rule ID:       ${input:ruleId:from the Migration Status table in docs/SPEC.md, e.g. SR030}
- Target check class:   ${input:className:from the Migration Status table, e.g. SqlInLoopCheck}

## Preconditions

Verify before starting:
1. The AST pipeline exists: `reviewer/engine/runner.py` imports cleanly
   and the test suite is green. If not, stop and tell the user to run
   `/scaffold-pipeline` first.
2. The legacy function `${input:legacyFn}` exists in `reviewer_legacy.py`.
3. The row for `${input:ruleId}` in `docs/SPEC.md` → Migration Status
   is not already `done`.

If any of these fail, stop and explain.

## Step 1 — Read the legacy function critically

Open `reviewer_legacy.py`, locate `${input:legacyFn}`, and produce
**three summaries** — show all three to the user before writing any code:

1. **What the check is trying to detect** (the *intent*). What quality
   issue does it exist to surface? Cite the SPEC row in `docs/SPEC.md`
   for `${input:ruleId}`.

2. **How the legacy implements it** (the *mechanism*). Brief — one
   paragraph. Note which fields of the `BizRule` it reads
   (`script`, `comment`, `scope`, `name`), what regex patterns it
   uses, and what state it tracks (loop depth, brace balance, etc.).

3. **What the legacy gets wrong**. Be specific. Categorize:
   - **False positives** — cases it flags that aren't real issues
     (e.g. matches inside comments or string literals, brace-counting
     bugs, regex matching substrings that aren't keywords).
   - **False negatives** — cases it misses (e.g. patterns that don't
     fit its regex, multi-line constructs the line-scanner can't see,
     nested structures it can't analyze).
   - **Shapes it can't analyze** — limitations of regex/line-scanning
     that prevent the check from doing what it should
     (e.g. operator-precedence in conditions, expression structure,
     reference resolution).

Then propose **what the AST version can do that the legacy can't**.
The AST gives you:
- Structural access (`BinaryOp.left` / `BinaryOp.right`, child nodes,
  type information from node kinds).
- Context tracking via `CheckContext` (loop stack, try stack).
- String/comment immunity by construction (tokenizer drops them).
- Recursive subtree walks via `node.children()`.

Use these. Do not constrain the AST version to only flag what the
legacy flags. The goal is the **strongest correct check**, not a
faithful port of legacy behavior.

**Wait for the user to confirm the plan before writing code.**

## Step 2 — Identify AST hooks

Decide which visitor methods the new check needs based on the *intent*
identified in Step 1, not the *mechanism* of the legacy. Common
patterns:

- Pattern matches **a specific node kind** → override `visit_<Kind>`.
- Pattern matches **a call to a specific built-in** → override
  `visit_Call` and filter on callee name.
- Pattern cares about **enclosing context** (inside a loop, inside a
  try) → use `self.ctx.in_loop()` / `self.ctx.in_try()`.
- Pattern is **whole-script** (e.g. "too few logs") → override
  `visit_Script` and walk once.
- Pattern is **structural across siblings** (e.g. dead code after a
  terminator) → override `visit_Block` and `visit_Script` and walk
  the statement list.
- Pattern needs **expression-tree analysis** (e.g. always-true
  conditions, expression complexity) → override `visit_<StmtKind>`
  for statements that hold the expression and analyze the
  `BinaryOp` / `UnaryOp` / literal nodes structurally.
- Pattern needs **graded severity** (e.g. risk levels based on what
  else is in the subtree) → use the `severity=` override on
  `self.ctx.emit()` and write helper functions that classify the
  context.

State your plan before implementing, including:
- Which visitor methods you'll override
- What helpers you'll extract (and whether they're reusable across
  checks)
- Whether the check needs new structural information added to
  `CheckContext` — if yes, propose the addition explicitly so it
  benefits future checks too
- How severity is determined (single severity, or graded)
- Any cases where the AST will catch issues the legacy misses
  (these become positive tests in Step 4)

Wait for confirmation before implementing.

## Step 3 — Implement the check

Create (or extend) `reviewer/checks/<category>.py` — the category must
match the one in `docs/SPEC.md`. Register with
`@register_check(rule_id=..., category=..., severity=..., description=...)`
and import the module from `reviewer/checks/__init__.py` if it's not
already.

Rules (reminder from the instructions file):
- No regex over `bizrule.script`. Use AST node properties only.
- `line` comes from a node (`node.line` or `node.callee.line`).
- Enclosing-context is read from `self.ctx`, not tracked per check.
- Docstring cites the SPEC row.
- Finding message includes the rule ID in brackets and mirrors the
  legacy message's useful parts (line, offending element) so humans
  who were used to the old output are not lost.

## Step 4 — Tests with intentional divergence

No, keep that. It's still relevant — both for the "preserve recall" tests and for the new "AST catches more" tests. New fixtures are needed either way, and the guidance to base them on real patterns from the sample packs is exactly right.
Just append the new framing above or below that paragraph, don't replace it.
Here's how the updated Step 4 would look (keeping your fixture instruction intact):
markdown## Step 4 — Tests with intentional divergence

The AST check is correct. The legacy is the reference, not the spec.
The diff-test contract is:
- **Recall preservation**: every legacy finding that is *actually correct* must also be flagged by the AST. If you can identify legacy false positives in a fixture, document them inline (excused list).
- **Improvement allowance**: if the AST catches issues the legacy misses, **add a positive test for each new case**. The diff-test should not penalize this — use a fixture-specific allow-list (`AST_EXTRAS_PER_FIXTURE`) if needed.

So the diff-test asserts:
(ast_lines - extras_for_this_fixture) ⊆ (legacy_lines - excused_legacy_fps_for_this_fixture)

Add to `tests/test_checks_<category>.py`:

1. **Positive** — fixture that triggers the issue; assert exactly
   the set of expected findings (rule_id, line, key message substring).
2. **Negative** — fixture where the issue is absent; assert that the
   check produced zero findings.
3. **Edge** — at minimum, a case where the pattern appears inside a
   comment AND inside a string literal. The AST pipeline must handle
   these correctly by construction; tests prove it.
4. **AST-improvement tests** — one positive test per case the AST
   catches that legacy missed. Document each clearly: "Legacy regex
   misses this because <reason>; the AST catches it via <mechanism>."
5. **Diff-test** — parametrized over every existing fixture, asserting
   the recall-preservation contract above.

Create fixtures under `tests/fixtures/smartrules/` in plain-text
BizRule-body style. Base them on real patterns from `sample_pack.xml`
and `sample_pack2.xml` where possible.

## Step 5 — Update the Migration Status table

In `docs/SPEC.md` → §8b, update the row for `${input:ruleId}`:
- `Status`: `done`
- `Diff-test clean?`: `yes` if the diff-test passes without any
  false-positive-excused case; otherwise `yes, with N excused FPs` and
  link to the test.

## Step 6 — Do NOT delete the legacy function yet

`reviewer_legacy.py` stays intact until every row in the Migration
Status table is `done`. The parallel execution in `main.py` continues.

## What you deliver at the end

1. New check class in `reviewer/checks/<category>.py`.
2. Import line added to `reviewer/checks/__init__.py` if needed.
3. Tests added: positive, negative, edge, diff.
4. One or more new fixtures in `tests/fixtures/smartrules/`.
5. Migration Status table updated.
6. A short summary message stating:
   - Which legacy function was migrated.
   - Which weaknesses of the legacy version the AST version fixes.
   - How many fixtures the diff-test covered, and whether every case
     agreed on line numbers.

Do NOT touch unrelated files. Do NOT add new rule IDs in this prompt —
use `/new-review-check` for brand-new checks.
