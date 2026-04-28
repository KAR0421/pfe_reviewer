---
description: "Add a new review check (AST-based) that has no legacy counterpart"
agent: "agent"
---
# /new-review-check

Add a brand-new review check in the AST pipeline. For migrating an
existing legacy check, use `/migrate-check` instead.

Inputs:
- Check topic:      ${input:topic:Short name, e.g. "array_alias"}
- What it detects:  ${input:what:One sentence}
- Spec category:    ${input:category:naming | docs | logic | perf | security | deps | logs | scope | lang}
- Rule ID:          ${input:ruleId:from docs/SPEC.md; if new, add a row there first}
- Severity:         ${input:severity:info | warning | error}

## Preconditions

1. The AST pipeline exists (`reviewer/engine/runner.py` imports and
   tests are green). If not, stop and direct the user to
   `/scaffold-pipeline`.
2. The rule ID has a row in either §6 (Review scope) or §8b (Migration
   Status) of `docs/SPEC.md`. If not, add a row to §6 first with a
   one-line description, then proceed.

## What to produce

Follow [`.github/instructions/ast-pipeline.instructions.md`](../instructions/ast-pipeline.instructions.md)
exactly.

1. **Check class** in `reviewer/checks/<category>.py`:
   - `@register_check(rule_id="${input:ruleId}", category="${input:category}", severity="${input:severity}", description=...)`
   - Subclass of `Check`.
   - Visitor methods on the AST node kinds that carry the pattern.
   - Docstring citing the SPEC row.
   - `self.ctx.emit(line=..., message=...)` to report findings.
   - No regex over raw script text. No re-implementation of loop/try
     tracking — use `self.ctx.in_loop()` / `self.ctx.in_try()`.

2. **Import** from `reviewer/checks/__init__.py` if the category module
   is new.

3. **Tests** in `tests/test_checks_<category>.py`:
   - Positive: fixture that triggers; assert rule_id + line numbers.
   - Negative: clean fixture; assert no findings for this rule_id.
   - Edge: pattern inside a comment AND inside a string — must NOT
     flag. (This is the whole point of using an AST; the test
     enforces it.)
   - Any other category-specific edge (empty script, long script,
     minified, nested).

4. **Fixtures** in `tests/fixtures/smartrules/` — plain BizRule
   bodies, styled like real scripts from `sample_pack.xml`.

5. **Docs**:
   - If the rule ID is not yet in `docs/SPEC.md` §6, add it.
   - If the category does not yet have a check module, mention that
     in the summary.

## Quality bar

- Think about which AST node is actually the pattern before writing
  any code. Write a one-line plan such as "visit `AssignStmt` where
  target is an `Identifier` and value is another `Identifier`, and
  both are known to be array-typed" — then implement.
- If the only way you can think to detect the pattern is "scan the
  source text with a regex", **stop and reconsider** — usually this
  means the pattern belongs elsewhere (tokenizer, parser, or
  `CheckContext`) rather than as regex in a check.
- If the check needs structural info not on the AST today (e.g. type
  inference, call graph), state the gap clearly before proceeding —
  the right move is often to extend the AST or `CheckContext` once and
  share that extension with future checks, rather than hack it into
  this one check.

## Deliverable summary

End your turn with a short message that states:
- The rule ID, class name, file path.
- Which AST nodes the check visits.
- How many tests + fixtures were added.
- Any decision (e.g. "extended `CheckContext` with `assigned_arrays`
  set") that future check authors should know about.
