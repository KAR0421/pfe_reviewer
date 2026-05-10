# BizRule Reviewer — Project Context

## What this project is
An internal tool (PFE project) that performs **automated code review on
BizRule scripts** extracted from XML `.pack` files produced by the IMPRESS
project (NeoXam DataHub-based product). The host product is written in Java,
but the scripts being reviewed are in a **company-specific scripting
language** (NeoXam SmartRule scripting). This reviewer is written in Python.

## What we are doing
Extending the AST-based BizRule reviewer with new checks per the SPEC,
integrating with Bitbucket pull requests, and building agentic checks for
semantic patterns that pure static analysis cannot reach (naming intent,
purpose mismatches, comment quality, hardcoded-secret detection).

## Pipeline
```
XML .pack file
    → XML Parser       (parser.py)
    → BizRule objects
    → Tokenizer → AST Parser → AST
    → Engine (visitor walk) → Findings
    → Reporter → Report
```

## Repo layout
- `main.py`                  — entry point.
- `parser.py`                — XML → BizRule extraction.
- `reviewer/`                — the AST pipeline:
    - `ast/{tokens,tokenizer,nodes,parser}.py`
    - `engine/{finding,registry,visitor,runner}.py`
    - `checks/<category>.py`
    - `reporters/{console,json_reporter}.py`
- `tests/`                   — pytest suite + `tests/fixtures/smartrules/`.
- `docs/SPEC.md`             — project spec + review scope.
- `docs/scripting-grammar.md` — authoritative language reference.

## Core data model
`BizRule` (in `parser.py`):
- `name`    — the `RULE_CODE` (e.g. `UPDATE_DOCUMENT_PROCESS`)
- `comment` — the `USER_COMMENT`
- `scope`   — the `FIND` attribute on `<SMARTRULE>`
- `script`  — the `IMPACT` CDATA content (the actual code to review)

## How new behaviour is added

When asked to add a review rule, a new check, or analysis logic:
1. Confirm the rule has a row in `docs/SPEC.md` §6 (add one if missing).
2. Add the check as a `Check` subclass in `reviewer/checks/<category>.py`
   following [`.github/instructions/ast-pipeline.instructions.md`](./instructions/ast-pipeline.instructions.md).
3. Use the `/new-review-check` prompt for the structural workflow.

## Reviewer output contract
```python
@dataclass(frozen=True)
class Finding:
    rule_id: str        # "SR###"
    category: str       # naming|docs|logic|perf|security|deps|logs|scope|lang
    severity: str       # info | warning | error
    line: int | None
    message: str
    bizrule: str        # the RULE_CODE

@dataclass(frozen=True)
class Report:
    rule_name: str
    findings: tuple[Finding, ...]
```

## Conventions
- Python 3.10+, type hints on public functions, docstrings explaining *why*.
- AST nodes, findings, and reports are `@dataclass(frozen=True)`.
- Every new check declares its rule id, category, severity via
  `@register_check(...)`; stable IDs live in the table in `docs/SPEC.md`.
- Every AST node carries a 1-based `line` — checks always include the
  line number of the offending node in the finding.
- Never change `BizRule` field names without also updating `parser.py`
  and any check that reads them.
- The tokenizer strips comments (both `//` and `/* ... */`) and
  tokenizes strings as single opaque tokens — checks **never** regex
  over raw script text.
- The parser fails soft: tokenize/parse errors surface as a synthetic
  `SR999` finding on the affected BizRule, not as a crash of the whole
  review.

## Review scope (summary — see `docs/SPEC.md` for the full list)
**Must Have:** naming conventions, minimal documentation, static logic
(always-true conditions, dead code), basic performance (SQL-in-loop,
nested loops, repeated queries, unbounded loops), security (null
handling, hardcoded secrets, div-by-zero), dependency references.
**Should Have:** trigger-scope verification, BizRule return-type checks,
version diff, log quality.
**Nice to Have:** ML pattern detection, refactoring hints, quality scoring.

## Things Copilot should NOT do
- Do not suggest using `xml.etree.ElementTree` directly on raw pack
  content — packs contain unescaped characters inside `<IMPACT>` CDATA.
  Use the regex extraction in `parser.py`.
- Do not rename `IMPACT`, `USER_COMMENT`, `RULE_CODE`, or other XML tags
  — they are fixed by the NeoXam schema (`schema.xml`).
- Do not invent new script-language keywords or syntax. The authoritative
  reference is `docs/scripting-grammar.md` (from `syntaxe.odt`). If a
  construct is not documented there, ask rather than guess — the right
  move is usually to extend the grammar doc and the parser together.
- Do not write checks that regex over the raw `bizrule.script` string.
  Checks operate on AST nodes; the tokenizer already removed comments
  and the parser already resolved structure.
- Do not output Bitbucket-specific formatting yet — the `bitbucket`
  reporter is a later milestone.
