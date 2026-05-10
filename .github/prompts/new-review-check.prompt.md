---
description: "Add a new AST-based review check, with a critical-thinking design phase before any code is written"
agent: "agent"
---
# /new-review-check

Add a new review check to the AST pipeline, following
[`.github/instructions/ast-pipeline.instructions.md`](../instructions/ast-pipeline.instructions.md).

Inputs:
- Rule ID:          ${input:ruleId:from `docs/SPEC.md` §6, e.g. SR033}
- Target check class: ${input:className:e.g. UnboundedLoopCheck}
- Spec category:    ${input:category:naming | docs | logic | perf | security | deps | logs | scope | lang}
- Severity:         ${input:severity:info | warning | error}

## Preconditions

Verify before starting:
1. The check's row exists in `docs/SPEC.md` §6. If it does not, stop and
   tell the user to add the row first (with description and severity).
2. The row's `Status` is `pending` (not `done`, not `agentic`).
3. No check class with the same `RULE_ID` is already registered in
   `reviewer/checks/`.

If any of these fail, stop and explain.

## Step 1 — Read the SPEC row critically

Open `docs/SPEC.md`, locate the row for `${input:ruleId}`, and produce
**three summaries** — show all three to the user before writing any code:

1. **What the check is trying to detect** (the *intent*). Quote the
   one-line description from the SPEC table, then expand: what real
   defect is this catching? What does a representative offending
   BizRule look like? Cite an example from `sample.pack.xml` or
   `sample.pack2.xml` if you can find one.

2. **What "in scope" means for this rule.** Be precise about the
   forms the rule does and does not flag. For example, if the rule is
   "unbounded loop", does `while (i < n)` count when `n` is a literal?
   When it's an identifier? When it's a function call? Pick a stance
   and justify it. The wrong stance now is cheaper than the wrong
   stance after merge.

3. **What the check is explicitly NOT.** Catalogue the adjacent
   patterns this rule must *not* fire on, to avoid false positives.
   Include at least:
   - Patterns that look similar inside string literals.
   - Patterns that look similar inside comments.
   - Patterns that look similar but are syntactically different
     (e.g. `for X := 1 to n do` is bounded by spec but `n` is a
     variable — does that count?).

**Wait for the user to confirm the plan before writing code.**

## Step 2 — Identify AST hooks

Decide which visitor methods the new check needs based on the
*intent* identified in Step 1, not on superficial syntax. Common
patterns:

- Pattern matches **a specific node kind** → override `visit_<Kind>`.
- Pattern matches **a call to a specific built-in** → override
  `visit_Call` and filter on callee name.
- Pattern cares about **enclosing context** (inside a loop, inside a
  try) → use `self.ctx.in_loop()` / `self.ctx.in_try()`.
- Pattern is **whole-script** (e.g. "too few logs", "any duplicate
  query") → override `visit_Script` and walk once, collecting state
  before reporting.
- Pattern is **structural across siblings** (e.g. dead code after a
  terminator) → override `visit_Block` and walk the statement list.
- Pattern needs **expression-tree analysis** (e.g. always-true
  conditions, expression complexity) → override `visit_<StmtKind>`
  for statements that hold the expression and analyze the
  `BinaryOp` / `UnaryOp` / literal nodes structurally.
- Pattern needs **graded severity** (e.g. risk levels based on what
  else is in the subtree) → use the `severity=` override on
  `self.ctx.emit()` and write helper functions that classify the
  context.

State your plan before implementing, including:
- Which visitor methods you'll override.
- What helpers you'll extract (and whether they're reusable across
  checks).
- Whether the check needs new structural information added to
  `CheckContext` — if yes, propose the addition explicitly so it
  benefits future checks too.
- How severity is determined (single severity, or graded).
- Any edge cases the check must explicitly handle (these become
  positive or edge tests in Step 4).

**Wait for confirmation before implementing.**

## Step 3 — Implement the check

Create or extend `reviewer/checks/<category>.py` — the category must
match the one in `docs/SPEC.md`. Register with
`@register_check(rule_id=..., category=..., severity=..., description=...)`
and import the module from `reviewer/checks/__init__.py` if it's not
already.

Rules (reminder from the instructions file):
- No regex over `bizrule.script`. Use AST node properties only.
- `line` comes from a node (`node.line` or `node.callee.line`).
- Enclosing-context is read from `self.ctx`, not tracked per check.
- Docstring cites the SPEC row.
- Finding message names the offending element clearly enough that a
  reviewer can act on it without re-reading the source.

## Step 4 — Tests

Add to `tests/test_checks_<category>.py`:

1. **Positive** — fixture that triggers the issue; assert exactly the
   expected set of findings (rule_id, line, key message substring).
2. **Negative** — fixture where the issue is absent; assert that the
   check produced zero findings for this rule_id.
3. **Edge** — at minimum, a case where the pattern appears inside a
   comment AND inside a string literal. The AST pipeline must handle
   these correctly by construction; tests prove it.
4. **Boundary tests** — for any threshold or graded-severity rule,
   one test that lands exactly on the boundary (silent) and one that
   lands one unit past it (fires). Document the boundary in the
   assertion.

Create fixtures under `tests/fixtures/smartrules/` in plain-text
BizRule-body style. Base them on real patterns from `sample.pack.xml`
and `sample.pack2.xml` where possible — the goal is for fixtures to
look like code that could plausibly land in a real pack.

## Step 5 — Update the Status table

In `docs/SPEC.md` §6, change the row's `Status` from `pending` to
`done`. If the rule has graded severity or any subtle policy choice,
add a footnote explaining it (see `[^sr031]`, `[^sr032]`, `[^sr091]`
for examples).

## What you deliver at the end

1. New check class in `reviewer/checks/<category>.py`.
2. Import line added to `reviewer/checks/__init__.py` if needed.
3. Tests added: positive, negative, edge, plus any boundary tests.
4. One or more new fixtures in `tests/fixtures/smartrules/`.
5. SPEC row updated to `done`, with footnote if needed.
6. A short summary message stating:
   - The rule ID, class name, file path.
   - Which AST nodes the check visits.
   - How many tests + fixtures were added.
   - Any decision (e.g. "extended `CheckContext` with `assigned_arrays`
     set") that future check authors should know about.

Do NOT touch unrelated files.
