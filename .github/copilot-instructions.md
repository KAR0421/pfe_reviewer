# BizRule Reviewer — Project Context

## What this project is
An internal tool (PFE project) that performs **automated code review on BizRule
scripts** extracted from XML `.pack` files produced by the IMPRESS project
(NeoXam DataHub-based product). The host product is written in Java, but the
scripts being reviewed are in a **company-specific scripting language** (NeoXam
SmartRule scripting). This reviewer is written in Python.

## Pipeline
```
XML .pack file  →  Parser  →  BizRule objects  →  Reviewer  →  Report
```
- Parser extracts `<SMARTRULE>` blocks from the XML, pulling `RULE_CODE`,
  `USER_COMMENT`, `DESCRIPTION`, `CONDITION`, `IMPACT` (the script), and
  trigger metadata.
- Reviewer runs a set of static checks against each BizRule script.
- Report is currently printed to the console; target output is **Bitbucket
  pull-request comments** in a later phase.

## Repo layout
- `main.py`            — entry point; glues parser and reviewer together
- `parser.py`          — extracts `SMARTRULE` blocks → `BizRule` objects
- `preprocessor.py`    — normalizes script text (strip blanks, comments)
- `reviewer.py`        — individual `check_*` functions + `review_bizrule`
- `xml_loader.py`      — alternative ElementTree-based loader
- `docs/SPEC.md`       — full project specification and review scope
- `docs/scripting-grammar.md` — syntax reference for the BizRule script language
- `.github/instructions/` — path-scoped Copilot rules
- `.github/prompts/`      — reusable Copilot slash-commands

## Core data model
`BizRule` (defined in `parser.py`):
- `name`    — the `RULE_CODE` (e.g. `UPDATE_DOCUMENT_PROCESS`)
- `comment` — the `USER_COMMENT`
- `scope`   — the `FIND` attribute on `<SMARTRULE>`
- `script`  — the `IMPACT` CDATA content (the actual code to review)

## Reviewer output contract
Each check returns `list[str]`; `review_bizrule(br)` returns:
```python
{"name": str, "issues": list[str]}
```
Planned evolution: a `Finding` dataclass with `rule_id`, `severity`
(`info|warning|error`), `line`, `message`, `category` (naming, logic,
performance, security, docs, deps).

## Conventions
- Python 3.10+, type hints on public functions, docstrings explaining *why*.
- Each new review check lives as a single `check_<topic>(...)` function in
  `reviewer.py` (or later, its own module under `reviewer/checks/`).
- Issues include a **line number** whenever one can be inferred.
- Never change `BizRule` field names without also updating `parser.py`,
  `xml_loader.py`, and any check that reads them.
- Parsing the target script language with regex is acceptable for now, but
  nothing should assume pretty-printed code (inline `if`s, mixed indentation,
  and CDATA artifacts all occur in real packs).

## Review scope (summary — see `docs/SPEC.md` for the full list)
**Must Have (automated):** naming conventions, minimal documentation,
static logic (always-true conditions, dead code), basic performance (unbounded
loops, repeated queries), security (null handling, hardcoded secrets, div-by-zero),
dependency references.
**Should Have:** trigger-scope verification, BizRule return-type checks,
version diff, log quality.
**Nice to Have:** ML pattern detection, refactoring hints, quality scoring.

## Things Copilot should NOT do
- Do not suggest using `xml.etree.ElementTree` directly on raw pack content —
  packs contain unescaped characters inside `<IMPACT>` CDATA; use the sanitizing
  approach in `xml_loader.py` or keep regex extraction in `parser.py`.
- Do not rename `IMPACT`, `USER_COMMENT`, `RULE_CODE`, or other XML tags — they
  are fixed by the NeoXam schema (`schema.xml`).
- Do not invent new script-language keywords. The authoritative syntax
  reference is `docs/scripting-grammar.md` (populated from the official
  `syntaxe.odt`). If a construct is not documented there, ask rather than
  guess.
- Do not output Bitbucket-specific formatting yet — the reporter abstraction
  does not exist. Keep check return values as plain message strings for now.
