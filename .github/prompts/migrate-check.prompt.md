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

## Step 1 — Read the legacy function

Open `reviewer_legacy.py`, locate `${input:legacyFn}`, and summarize in
plain English:
- What pattern it detects.
- What message format it emits.
- Which fields of the `BizRule` it reads (just `script`? also `comment`,
  `scope`?).
- Which lines it reports (1-based? 0-based + 1?).
- Known weaknesses (e.g. false positives on strings/comments, brace
  desync — these are expected, we're fixing them by going to AST).

Show this summary to the user before writing code.

## Step 2 — Identify AST hooks

Decide which visitor methods the new check needs. Common patterns:
- Pattern matches **a specific node kind** → override `visit_<Kind>`.
- Pattern matches **a call to a specific built-in** → override
  `visit_Call` and filter on callee name.
- Pattern cares about **enclosing context** (inside a loop, inside a
  try) → use `self.ctx.in_loop()` / `self.ctx.in_try()`.
- Pattern is **whole-script** (e.g. "too few logs") → override
  `visit_Script` and walk once.

State your plan before implementing.

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

## Step 4 — Tests

Add to `tests/test_checks_<category>.py`:

1. **Positive** — fixture that triggers the issue; assert the check
   produces findings at the expected line numbers with the expected
   rule_id.
2. **Negative** — fixture without the issue; assert no findings.
3. **Edge** — at minimum, a case where the pattern appears inside a
   comment AND inside a string literal. The AST pipeline must not flag
   those. A legacy-vs-new diff here will likely diverge (legacy: false
   positive; new: clean); **this is the improvement, note it in the
   test docstring**.
4. **Diff-test** — parametrized over every existing fixture, asserting
   that the new check's lines are a **subset** of the legacy check's
   lines. (Superset is wrong; the new pipeline should not regress
   recall. Finding *fewer* issues is expected only when those legacy
   findings were false positives — note each such case explicitly in
   the test.)

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
