# BizRule Reviewer — Project Context

## What this project is
An internal tool (PFE project) that performs **automated code review on BizRule
scripts** extracted from XML `.pack` files produced by the IMPRESS project
(NeoXam DataHub-based product). The host product is written in Java, but the
scripts being reviewed are in a **company-specific scripting language** (NeoXam
SmartRule scripting). This reviewer is written in Python.

## Pipeline (target)
```
XML .pack file
    → XML Parser       (parser.py / xml_loader.py)
    → BizRule objects
    → Tokenizer → AST Parser → AST
    → Engine (visitor walk) → Findings
    → Reporter → Report
```

## Repo layout (target)
- `main.py`                  — entry point; runs BOTH pipelines during migration
- `parser.py` / `xml_loader.py` — XML ingestion (unchanged by this refactor)
- `preprocessor.py`          — legacy; being retired
- `reviewer_legacy.py`       — the original flat regex-per-check implementation
                               (renamed from `reviewer.py`; retained until
                               every check has a migrated counterpart)
- `reviewer/`                — the new AST-based pipeline
    - `ast/{tokens,tokenizer,nodes,parser}.py`
    - `engine/{finding,registry,visitor,runner}.py`
    - `checks/<category>.py`
    - `reporters/{console,json_reporter}.py`
- `docs/SPEC.md`             — project spec + review scope + migration table
- `docs/scripting-grammar.md` — authoritative language reference
- `docs/adr/0001-reviewer-architecture.md` — design decision record

## Core data model
`BizRule` (in `parser.py`):
- `name`    — the `RULE_CODE` (e.g. `UPDATE_DOCUMENT_PROCESS`)
- `comment` — the `USER_COMMENT`
- `scope`   — the `FIND` attribute on `<SMARTRULE>`
- `script`  — the `IMPACT` CDATA content (the actual code to review)

## Target architecture — IMPORTANT for every new change

**The flat `reviewer_legacy.py` is frozen.** No new checks, no new features.
Bugs that block real usage may still be fixed there, but the long-term
direction is the AST pipeline described in
[`docs/adr/0001-reviewer-architecture.md`](../docs/adr/0001-reviewer-architecture.md).

When asked to add a review rule, a new check, or analysis logic:
1. Check whether the AST pipeline (`reviewer/` package) has been scaffolded.
2. If not, **do not extend `reviewer_legacy.py`** — point the user to the
   `/scaffold-pipeline` prompt instead.
3. If the pipeline exists, add the check as a `Check` subclass in
   `reviewer/checks/<category>.py` following the pattern in
   [`.github/instructions/ast-pipeline.instructions.md`](./instructions/ast-pipeline.instructions.md).

## Reviewer output contract
Target (AST pipeline):
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
    score: int | None = None
```
Legacy shape (still returned by `reviewer_legacy.review_bizrule`):
`{"name": str, "issues": list[str]}` — do not use this shape in new code.

## Conventions
- Python 3.10+, type hints on public functions, docstrings explaining *why*.
- AST nodes, findings, and reports are `@dataclass(frozen=True)`.
- Every new check declares its rule id, category, severity via
  `@register_check(...)`; stable IDs live in the table in `docs/SPEC.md`.
- Every AST node carries a 1-based `line` — checks always include the line
  number of the offending node in the finding.
- Never change `BizRule` field names without also updating `parser.py`,
  `xml_loader.py`, and any check that reads them.
- The tokenizer strips comments and tokenizes strings as single opaque
  tokens — checks **never** regex over raw script text.
- The parser fails soft: tokenize/parse errors surface as a synthetic
  `SR999` finding on the affected BizRule, not as a crash of the whole
  review.

## Review scope (summary — see `docs/SPEC.md` for the full list)
**Must Have (automated):** naming conventions, minimal documentation,
static logic (always-true conditions, dead code), basic performance (unbounded
loops, repeated queries), security (null handling, hardcoded secrets,
div-by-zero), dependency references.
**Should Have:** trigger-scope verification, BizRule return-type checks,
version diff, log quality.
**Nice to Have:** ML pattern detection, refactoring hints, quality scoring.

## Things Copilot should NOT do
- Do not extend `reviewer_legacy.py` with new behavior. If a new check is
  requested and the AST pipeline is not in place, run `/scaffold-pipeline`
  first.
- Do not suggest using `xml.etree.ElementTree` directly on raw pack content —
  packs contain unescaped characters inside `<IMPACT>` CDATA; use the
  sanitizing approach in `xml_loader.py` or keep regex extraction in
  `parser.py`.
- Do not rename `IMPACT`, `USER_COMMENT`, `RULE_CODE`, or other XML tags —
  they are fixed by the NeoXam schema (`schema.xml`).
- Do not invent new script-language keywords or syntax. The authoritative
  reference is `docs/scripting-grammar.md` (from `syntaxe.odt`). If a
  construct is not documented there, ask rather than guess — the right move
  is usually to extend the grammar doc and the parser together.
- Do not write checks that regex over the raw `bizrule.script` string. In
  the new pipeline, checks operate on AST nodes; the tokenizer already
  removed comments and the parser already resolved structure.
- Do not output Bitbucket-specific formatting yet — the `bitbucket` reporter
  is a later milestone.
