---
description: "Scaffold a new review check for the BizRule reviewer"
agent: "agent"
---
Your goal is to scaffold a new review check in `reviewer.py` (or a new
module under `reviewer/checks/` if that package has already been introduced).

Ask the user (via `#tool:vscode/askQuestions` or `${input:...}` below) for
any info you do not have.

- Check topic:    ${input:topic:Short name, e.g. "unbounded_loops"}
- What it detects: ${input:what:One-sentence description of the issue}
- Spec item:      ${input:specItem:Which item in docs/SPEC.md (e.g. "Must Have → Basic performance")}
- Rule ID:        ${input:ruleId:Next free ID from the table in docs/SPEC.md, e.g. "SR010"}
- Severity:       ${input:severity:info | warning | error}
- Needs the full BizRule (not just the script)? ${input:needsBizrule:yes | no}

Follow the conventions in `.github/instructions/reviewer.instructions.md`:

1. Implement `check_<topic>` with a docstring explaining **why** it exists
   (link it to the spec item above).
2. Emit issue messages in the format used by existing checks, including the
   rule ID in brackets: `"[${input:ruleId}] <what> at line <N>: <line>"`.
3. Use `enumerate(lines, 1)` for 1-based line numbers.
4. Reuse any existing helper (e.g. the loop pattern); do not duplicate it.
   If no helper exists yet but this is the third+ place needing it,
   extract one.
5. Register the check inside `review_bizrule` in the correct category
   group (documentation → naming → static logic → dead code → performance
   → security → dependencies).
6. Add tests in `tests/test_checks.py` covering: one positive case, one
   negative case, and one edge case. Put any realistic BizRule scripts
   needed as fixtures in `tests/fixtures/*.smartrule`.
7. Add a row to the Review Checks table in `docs/SPEC.md` with the rule ID,
   category, severity, and a one-line description.

Do not invent new script-language syntax — refer to
`docs/scripting-grammar.md`. If the check needs a keyword that is not
documented there, stop and flag it to the user before proceeding.
