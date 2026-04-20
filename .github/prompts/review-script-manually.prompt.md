---
description: "Manually review a BizRule script snippet against the Must/Should Have scope"
agent: "ask"
---
You are acting as the BizRule reviewer in human form. Review the following
script against the checks listed in `docs/SPEC.md` (Must Have, then Should
Have). Use the syntax reference in `docs/scripting-grammar.md`.

Script:
```
${input:script:Paste the IMPACT content of the BizRule here}
```

Additional context (optional):
- RULE_CODE:      ${input:ruleCode:e.g. UPDATE_DOCUMENT_PROCESS}
- USER_COMMENT:   ${input:userComment:(paste here or leave blank)}

Produce your review as:

1. **Summary** — 1–2 sentences on what the rule does (in your words).
2. **Findings table** — rule_id, category, severity, line, message. Only
   include a finding if the issue is genuinely present; do not pad the
   table to look thorough.
3. **Not flagged but worth a human look** — items that are ambiguous (e.g.
   a query looks repeated but might be intentional).
4. **Suggested refactor sketch** — high-level only, no full rewritten code
   (per the "Refactoring intelligent — pas de suggestion de solution"
   guideline in the spec).

Do not invent syntax. If the script uses a keyword or built-in not listed
in `docs/scripting-grammar.md`, mention it explicitly in your review rather
than guessing its semantics.
