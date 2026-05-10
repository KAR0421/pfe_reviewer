---
description: "Add a test case (fixture + test) for an existing AST review check"
agent: "agent"
---
# /add-test-case

Add a new test case for an existing review check in
`reviewer/checks/*.py`.

Inputs:
- Check name:   ${input:check:AST class name, e.g. SqlInLoopCheck}
- Kind of case: ${input:kind:positive | negative | edge}
- Scenario:     ${input:scenario:Describe what the test demonstrates}

## Step 1 — Locate the check

Find the class in `reviewer/checks/*.py`. The matching test file is
`tests/test_checks_<category>.py`. If the class does not exist, stop
and ask whether the user meant `/new-review-check` instead.

## Step 2 — Create the fixture

Fixtures live in `tests/fixtures/smartrules/` as plain text files
holding just the `IMPACT` body (not wrapped in XML). Name the fixture
descriptively, e.g. `sql_in_foreach.smartrule`,
`static_condition_in_comment.smartrule`.

Model the style on real scripts from `sample.pack.xml` /
`sample.pack2.xml`:
- `:=` assignments (and `?=` where it's the scenario being tested)
- `// comment` lines (mixed French/English is realistic)
- `foreach var in list do { ... }` blocks
- SQL strings built by `+` concatenation
- `getSqlData(...)`, `getObjects(...)`, `msginfo(...)`, etc.

For **edge cases** involving comments or strings, include the
pattern-of-interest *inside* the comment or the string literal — this
is exactly where the AST pipeline must not produce a false positive.

## Step 3 — Write the test

```python
# tests/test_checks_<category>.py
from pathlib import Path
from reviewer.engine.runner import run_review

FIXTURES = Path(__file__).parent / "fixtures" / "smartrules"


def test_<check>_<scenario>():
    script = (FIXTURES / "<fixture_name>.smartrule").read_text()
    br = FakeBizRule(name="TEST_RULE", comment="test", scope="", script=script)
    findings = [f for f in run_review(br).findings if f.rule_id == "SR###"]

    # Positive:
    assert len(findings) == <N>
    assert findings[0].line == <L>
    assert "<key substring>" in findings[0].message

    # Negative / edge:
    # assert findings == []
```

For **edge** tests, include a comment on the assertion explaining why
the check stays silent (e.g. "AST pipeline: strings/comments are
opaque tokens").

## Step 4 — What NOT to do in this prompt

- Do not modify the check itself. If the test reveals a bug in the
  check, stop and report it to the user — that is a separate task.
- Do not add a new rule_id. If the scenario exposes a behavior the
  current rule doesn't cover, that's a new check (`/new-review-check`).

## Deliverable

End with a short message listing:
- The fixture file(s) added.
- The test function(s) added.
- Whether every added test passes locally. If any fails, explain what
  the failure implies (likely a check bug — flag for follow-up).
