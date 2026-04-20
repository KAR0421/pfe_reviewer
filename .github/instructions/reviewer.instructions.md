---
name: "Reviewer conventions"
description: "How to write, structure, and test review checks"
applyTo: "reviewer.py,reviewer/**,tests/test_reviewer*.py,tests/test_checks*.py"
---

# Reviewer conventions

## Shape of a check
Every check is a pure function:
```python
def check_<topic>(script: str) -> list[str]:
    """One-line summary. Explain WHY this check exists (which spec item)."""
    issues: list[str] = []
    # ...
    return issues
```
If the check needs the full `BizRule` (for `comment`, `scope`, `name`), accept
`bizrule` instead of `script`:
```python
def check_minimal_documentation(bizrule) -> list[str]: ...
```

## Issue message format
```
"<CATEGORY>: <what> at line <N>: <offending line snippet>"
```
Examples (already in the codebase):
- `"Generic variable names found: tmp1, varX"`
- `"Dead code after terminator 'return' at line 50: msginfo(\"Never executed\")"`
- `"SQL query inside loop starting at line 53: line 54 -> SELECT ..."`

Always include a **line number** when one can be inferred. Use 1-based line
numbers (`enumerate(lines, 1)`), consistently across checks — the existing
`check_dead_code` uses `i+1` on a 0-based enumeration, which is equivalent
but easier to get wrong; prefer `enumerate(lines, 1)` in new code.

## Registering a check
Add a single line in `review_bizrule` in `reviewer.py`:
```python
report["issues"].extend(check_<topic>(bizrule.script))
```
Keep the call order grouped by category: documentation → naming → static
logic → dead code → performance → security → dependencies.

## Shared helpers (use these, don't duplicate)
Three checks currently re-implement loop detection
(`check_logs`, `check_sql_in_loops`, `check_nested_loops`). When adding
loop-aware checks, extract a shared helper:
```python
LOOP_PATTERN = re.compile(r'\b(for|foreach|while|do)\b', re.IGNORECASE)

def iter_loop_spans(lines: list[str]) -> Iterator[tuple[int, int]]:
    """Yield (start_line, end_line) 1-based spans for each top-level loop."""
```
Do not track brace depth by counting `}` on a line alone — some real scripts
put `}` at the end of a statement line. If needed, use a small tokenizer.

## Future direction: `Finding` dataclass
Checks will migrate from `list[str]` to `list[Finding]`:
```python
@dataclass
class Finding:
    rule_id: str           # e.g. "SR007"
    category: str          # naming|docs|logic|perf|security|deps|logs
    severity: str          # info|warning|error
    line: int | None
    message: str
```
When adding a new check now, pick a **stable** rule id from the table in
`docs/SPEC.md` and include it in the issue string (e.g. `"[SR007] ..."`) so
migration is mechanical later.

## Tests
Every check must have a test in `tests/test_checks.py`:
- One positive case (issue detected)
- One negative case (clean script, no issues)
- One edge case (empty script, comments only, minified on one line)

Fixtures live in `tests/fixtures/*.smartrule` — plain text files holding just
the script body. Use the samples in `sample_pack.xml` / `sample_pack2.xml`
as a starting point for realism.

## Preprocessor usage
`preprocessor.preprocess_script` returns a **list of stripped non-empty
non-`//`-comment lines**. It does **not** preserve line numbers. Do not use
it for line-based checks; use `script.splitlines()` directly. It is a good
fit only for structural checks that do not care about position (e.g.
"is there any log call at all?").
