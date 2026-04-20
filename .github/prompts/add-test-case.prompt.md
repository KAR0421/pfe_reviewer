---
description: "Add a test case (fixture + test) for a reviewer check"
agent: "agent"
---
Add a new test case for an existing review check.

- Check function: ${input:check:e.g. check_sql_in_loops}
- Kind of case:   ${input:kind:positive | negative | edge}
- What the case shows: ${input:scenario:Describe the scenario}

Requirements:

1. Create a fixture file under `tests/fixtures/` with a realistic BizRule
   script body (not wrapped in XML — just the `IMPACT` content). Name it
   descriptively, e.g. `sql_in_foreach.smartrule`. Model the style on real
   scripts from `sample_pack.xml` / `sample_pack2.xml`: `:=` assignments,
   `//` comments, `foreach ... in ... do { ... }`, strings concatenated
   with `+`, `getSqlData(...)`.
2. Add a test in `tests/test_checks.py` that loads the fixture and asserts
   the expected issues list (or empty list for a negative case).
3. The assertion should be **specific**: check the count of issues and
   that each expected issue string contains the right line number and a
   key substring (e.g. `"inside loop"`).
4. Do not modify the check itself in this task. If the test reveals a bug
   in the check, stop and report it to the user separately.

Use the conventions in `.github/instructions/reviewer.instructions.md`.
