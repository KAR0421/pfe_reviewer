---
description: "Add a test case (fixture + test) for a reviewer check"
agent: "agent"
---
# /add-test-case

Add a new test case for an existing review check. Works for both AST
pipeline checks (`reviewer/checks/*.py`) and legacy checks
(`reviewer_legacy.py`), but **prefer AST-pipeline tests** whenever the
check exists in both — the legacy tests go away with
`reviewer_legacy.py` once migration completes.

Inputs:
- Check name:   ${input:check:AST class name (e.g. SqlInLoopCheck) OR legacy function name (e.g. check_sql_in_loops)}
- Kind of case: ${input:kind:positive | negative | edge | diff}
- Scenario:     ${input:scenario:Describe what the test demonstrates}

## Step 1 — Locate the check

- If the name is CamelCase → AST check. Find the class in
  `reviewer/checks/*.py`. Test file is
  `tests/test_checks_<category>.py`.
- If the name is `check_snake_case` → legacy check. Test file is
  `tests/test_reviewer_legacy.py`.

If the check name does not match either, stop and ask.

## Step 2 — Create the fixture

Fixtures live in `tests/fixtures/smartrules/` as plain text files
holding just the `IMPACT` body (not wrapped in XML). Name the fixture
descriptively, e.g. `sql_in_foreach.smartrule`,
`static_condition_in_comment.smartrule`.

Model the style on real scripts from `sample_pack.xml` /
`sample_pack2.xml`:
- `:=` assignments (and `?=` where it's the scenario being tested)
- `// comment` lines (mixed French/English is realistic)
- `foreach var in list do { ... }` blocks
- SQL strings built by `+` concatenation
- `getSqlData(...)`, `getObjects(...)`, `msginfo(...)`, etc.

For **edge cases** involving comments or strings, include the
pattern-of-interest *inside* the comment or the string literal — this is
exactly where the AST pipeline must not produce a false positive.

## Step 3 — Write the test

### For AST-pipeline checks
```python
# tests/test_checks_<category>.py
from pathlib import Path
from reviewer.engine.runner import run_review
from parser import BizRule   # or wherever BizRule lives

FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"

def test_<check>_<scenario>():
    script = (FIXTURES / "<fixture_name>.smartrule").read_text()
    br = BizRule(name="TEST_RULE", comment="test", scope="", script=script)
    report = run_review(br)
    findings = [f for f in report.findings if f.rule_id == "SR###"]

    # For positive:
    assert len(findings) == <N>
    assert findings[0].line == <L>
    assert "<key substring>" in findings[0].message

    # For negative:
    # assert findings == []

    # For edge (pattern-in-comment / pattern-in-string):
    # Document WHY this is expected to be clean in a comment on the assertion
    # assert findings == []  # AST pipeline: strings/comments are not scanned
```

### For legacy checks
```python
# tests/test_reviewer_legacy.py
from pathlib import Path
from reviewer_legacy import <check_fn>

FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"

def test_<check_fn>_<scenario>():
    script = (FIXTURES / "<fixture_name>.smartrule").read_text()
    issues = <check_fn>(script)

    # For positive:
    assert len(issues) == <N>
    assert "<key substring>" in issues[0]
    assert "line <L>" in issues[0]  # if the check includes line numbers

    # For negative:
    # assert issues == []
```

### For diff-tests (kind = "diff")
Parametrized over every fixture, asserting the AST check's flagged
line numbers are a subset of the legacy check's, plus explicit allow-list
for false-positives the legacy version had. Document each excused case
inline.

```python
import pytest

@pytest.mark.parametrize("fixture", list(FIXTURES.glob("*.smartrule")))
def test_<check>_matches_legacy(fixture):
    script = fixture.read_text()
    br = BizRule(name="T", comment="", scope="", script=script)

    legacy_issues = check_<legacy_fn>(script)
    legacy_lines  = extract_lines(legacy_issues)  # helper

    ast_findings = [f for f in run_review(br).findings if f.rule_id == "SR###"]
    ast_lines    = {f.line for f in ast_findings}

    # Excused legacy false positives for this fixture:
    excused = FIXTURE_EXCUSED_FPS.get(fixture.name, set())
    assert ast_lines == (legacy_lines - excused), (
        f"AST and legacy disagree on {fixture.name}: "
        f"ast={ast_lines}, legacy={legacy_lines}, excused={excused}"
    )
```

## Step 4 — What NOT to do in this prompt

- Do not modify the check itself. If the test reveals a bug in the
  check, stop and report it to the user — that is a separate task.
- Do not add a new rule_id. If the scenario exposes a behavior the
  current rule doesn't cover, that's a new check (`/new-review-check`).
- Do not delete the legacy counterpart or mark a migration row `done`.
  That's the job of `/migrate-check`.

## Deliverable

End with a short message listing:
- The fixture file(s) added.
- The test function(s) added.
- Whether every added test passes locally. If any fails, explain what
  the failure implies (likely a check bug — flag for follow-up).
