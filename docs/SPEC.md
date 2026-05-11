# BizRule Reviewer — Specification

## 1. Context
The IMPRESS project (internal, built on the NeoXam DataHub product) ships
features as XML **`.pack` files**. Each pack contains business objects:
BizRules (`<SMARTRULE>`), classes, lists, and more. Each BizRule carries a
script in its `<IMPACT>` element, written in a **company-specific scripting
language** executed by the product (a Java application).

Today these scripts are difficult to review:
- XML-level diffs are unreadable.
- There is no history built into the pack format.
- The impact of a change is rarely obvious from the diff alone.
- Review is currently manual, slow, and inconsistent between reviewers.

This reviewer is an AST-based static analyzer: it tokenizes and parses each
BizRule script into an AST, then walks the tree once with a registry of
checks that emit structured findings.

## 2. Goal
Build a tool that:
1. **Extracts** BizRules from XML pack files.
2. **Analyzes** the scripts against a fixed scope of quality checks.
3. **Emits** a structured report of findings.
4. **Integrates** with Bitbucket pull requests to post the report as
   inline comments.

## 3. Non-goals
- Rewriting or auto-fixing scripts (the team explicitly wants no
  solution suggestions — only detection and optional refactor *hints*).
- Executing or simulating scripts dynamically.
- Parsing or validating non-BizRule objects in the pack (classes, lists) —
  except insofar as they are referenced by BizRules for dependency checks.
- Replacing the NeoXam editor or the product itself.

## 4. Architecture

```
XML .pack
    │
    ▼
BizRule extraction (parser.py)
    │
    ▼
tokenize  →  parse  →  AST
                         │
                         ▼
                engine visitor walks the tree once,
                dispatching every node to every registered check
                         │
                         ▼
                     Findings
                         │
                         ▼
                     reporter (console / JSON / Bitbucket)
```

### Modules
- `parser.py`   — extracts `<SMARTRULE>` blocks from the pack.
- `main.py`     — CLI entry point.
- `reviewer/`   — the AST pipeline:
    - `ast/{tokens,tokenizer,nodes,parser}.py`
    - `engine/{finding,registry,visitor,runner}.py`
    - `checks/<category>.py` — one module per category.
    - `reporters/{console,json_reporter}.py`

## 5. Data model
```python
class BizRule:
    name:    str   # RULE_CODE
    comment: str   # USER_COMMENT
    scope:   str   # FIND attribute
    script:  str   # IMPACT CDATA
```
Planned additions: `description`, `trigger_type`, `trigger_object`,
`rule_category`, `update_date`, `user`, `active`.

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
Note: a `Finding.score` field is planned for M5 (scoring) — not present today.

## 6. Review scope
Translated and expanded from `docs/review-scope.pdf`. Rule IDs are
stable; pick the next free ID when adding a new check.

| Status      | Meaning                                           |
|-------------|---------------------------------------------------|
| done        | Implemented, tests passing                        |
| pending     | Must-Have, scheduled in M2                        |
| should-have | Scheduled in M4 (DB-connected or harder)          |
| agentic     | Scheduled in M5 (LLM-driven)                      |

### Must Have — automated, mandatory

#### Naming & conventions
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR001 | warning  | Generic / ambiguous variable names (`tmp1`, `varX`, `temp`). | agentic |
| SR002 | warning  | BizRule `RULE_CODE` does not follow project naming convention. | pending |
| SR003 | info     | Rule name / code mismatch with its documented purpose. | agentic |

#### Minimal documentation
| ID      | Severity | Description | Status |
|---------|----------|-------------|--------|
| SR010   | error    | Missing or empty `USER_COMMENT`. | done |
| SR011   | warning  | Missing SMARTRULE_NAME: the rule has no display name in any language. Lenient — at least one language is enough. | pending |
| SR012.1 | warning  | Insufficient inline comment density: fewer than 1 `//` comment per 12 branches/loops/risky calls. Complexity definition same as SR091 (branches + loops + risky_calls). [^sr012_1] | done |
| SR012.2 | info     | Comments describe *how* instead of *why*. | agentic |

#### Static logic
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR020 | error    | Condition is always true / always false (two literals, same var both sides, or a literal-vs-literal sub-expression hidden inside `and`/`or`). [^sr020] | done |
| SR021 | warning  | Dead code after `return` / `abort` / `skip`. | done |

#### Basic performance
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR030 | error    | SQL query (`getSqlData`) executed inside a loop. | done |
| SR031 | warning  | Nested loops (two or more levels). [^sr031] | done |
| SR032 | warning  | Duplicate / near-duplicate queries in the same rule. [^sr032] | done |
| SR033 | warning  | Unbounded or trivially infinite loop. [^sr033] | done |
| SR034 | info     | Repeated reads of the same field on the same object without intervening reassignment (e.g. `x := obj.F; y := obj.F;` — caching `obj.F` once would be cleaner). | pending |

#### Security & robustness
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR040 | error    | Hardcoded business-sensitive literal (ID, threshold, name, label, file path, magic number). An agent reviews each non-trivial literal in context to decide whether it should be parameterized. | agentic |
| SR041 | error    | Division where the right operand could be zero. | pending |
| SR042 | warning  | Field access on a value that has not been guarded against null or empty. The check tracks both `if (obj != null) { ...obj.F... }` (then-branch guard) and `if (obj = null) { ... } else { ...obj.F... }` (else-branch guard) — guard tracking is structural via the engine's branch awareness. | pending |
| SR043 | warning  | Risky call (`getSqlData`, `callService`, `getObjects`, `obj.set`, `obj.method(...)`) not wrapped in a `try { } onerror { }` block. [^sr043] | should-have |
| SR044 | warning  | Dynamic SQL string passed to `getSqlData` / `getData` (SQL-injection shape). Fires on `getSqlData(queryStr)` where `queryStr` is computed elsewhere, or on concatenations whose non-literal pieces sit in structural positions (e.g. `"SELECT * FROM " + tableName + " WHERE ..."`). [^sr044] | pending |

#### Dependencies
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR051 | warning  | Cross-dependency (BR A calls BR B which calls A). | pending |
| SR052 | info     | BizRule references an object that exists only partially (e.g. missing field). | pending |

#### Language semantics (revealed by `syntaxe.odt`)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR055 | warning  | Array alias: `b := a` between array-typed variables with no subsequent `arraycopy` — mutations to `b` will affect `a`. | pending |
| SR057 | info     | Variables in the same rule differing only in case (e.g. `contrib` and `Contrib`) — likely typo since names are case-sensitive. | pending |
| SR058 | info     | Unintended record auto-create: assignment to `obj.FIELD[COND] := v` without an existence check first. The kernel silently creates a record when none matches. | pending |
| SR059 | info     | Unused variable: assigned (`x := 1`) but never read. [^sr059] | done |

#### Scope (technical)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR060 | warning  | `SMARTRULE_TRIGGER` empty or malformed. | pending |
| SR061 | warning  | `TRIGGER_OBJECT` not present in the pack (intra-pack lookup; DB-connected variant is M4). | pending |
| SR062 | info     | `TRIGGER_TYPE` code does not match a known enum value. [^sr062] | pending |

#### Logs
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR090 | warning  | Verbose log call inside a loop. | done |
| SR091 | info     | Long script with insufficient log density relative to its branching / loop / risky-call complexity. [^sr091] | done |
| SR093 | error    | Empty `onerror` block: `try { ... } onerror { }` swallows errors silently. | done |
| SR094 | warning  | `onerror` block doesn't engage with the implicit `error` (ScriptError) object — no `error.<method>` or `error.<field>` access anywhere in the block. Log calls (`msginfo`/`msgerror`/`msgwarn`) are additional visibility, not error handling. Without engaging `error.consume()` or `error.getMessage()` or similar, the exception is not consumed — even if logged, the runtime may keep propagating it. | done |

### Should Have — DB-connected or harder, scheduled in M4

#### Static logic (deferred)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR022 | info     | Pre-conditions placed after computations (suboptimal ordering). | should-have |

#### Dependencies (DB-connected)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR050 | error    | BizRule / class / list referenced but not in the pack or the reference. | should-have |

#### Return-type usage
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR070 | info     | Return type of a called BizRule cannot be inferred. | should-have |
| SR071 | warning  | Return value of a called BizRule is ignored. | should-have |
| SR072 | warning  | Return value is used inconsistently with its declared type. | should-have |

#### Version comparison
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR080 | info     | Rule has changed vs. previous version. | should-have |
| SR081 | warning  | Logic change detected (not just whitespace / comments). | should-have |
| SR082 | error    | Possible involuntary overwrite of a newer version. | should-have |

#### Logs (deferred)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR092 | info     | Log call emits only a constant string (no key values). | should-have |

### Nice to Have — bonus
- **AI / ML pattern detection** — flag known-risky constructs via a
  trained classifier. No rule IDs assigned yet.
- **Refactoring hints** — propose *hints* only (complexity hotspots,
  repeated blocks worth extracting). Do not generate replacement code.
- **Advanced scoring** — global score (0–100), per-category sub-scores,
  `merge safe / risky` indicator.

### M2 build order
The remaining Must-Have checks ship in this order:

1. SR057 — case-typo variables
2. SR034 — repeated field reads
3. SR044 — dynamic SQL
4. SR055 — array alias
5. SR058 — unintended record auto-create
6. SR011 — missing SMARTRULE_NAME
7. SR060 — empty/malformed SMARTRULE_TRIGGER
8. SR061 — TRIGGER_OBJECT not in pack (intra-pack only; DB variant is M4)
9. SR062 — TRIGGER_TYPE not in valid enum set
10. SR042 — guarded field access (flow analysis)
11. SR041 — div by zero (flow analysis)
12. SR002 — RULE_CODE convention regex (config-driven)

## 7. Output

### Phase A — console (current)
Text block per BizRule; numbered list of findings; `"no issues found."`
when clean.

### Phase B — structured
JSON matching the `Report` dataclass above, one object per rule, dumped
to stdout or a file.

### Phase C — Bitbucket integration
Post findings as inline PR comments, one per finding at its line number.
Requires Bitbucket REST API credentials, a mapping from pack file +
line to the PR diff, and a batch-comment strategy (probably one summary
comment + inline for `severity >= warning`).

## 8. Milestones

- **M1 — done.** AST pipeline shipped: tokenizer, parser, engine, thirteen
  checks (SR010, SR012.1, SR020, SR021, SR030, SR031, SR032, SR033,
  SR059, SR090, SR091, SR093, SR094), full test suite green.
- **M2 — current.** Finish the remaining structural Must-Have checks
  in the order documented in §6 "M2 build order" (SR057,
  SR034, SR044, SR055, SR058, SR011, SR060, SR061-intra, SR062, SR042,
  SR041, SR002).
- **M3 — Bitbucket integration.** Post findings as PR comments via the
  Bitbucket REST API; CI hook.
- **M4 — DB-connected and harder checks.** SR043 (after redefining
  which contexts warrant the warning), SR050, SR051, SR052, the
  DB-connected variant of SR061, return-type checks (SR070–SR072),
  version diff (SR080–SR082), SR022 (promoted out of M2), and SR092.
- **M5 — Agentic checks and quality.** LLM-driven checks for the
  semantic patterns marked `agentic` in §6 (SR001, SR003, SR012.2,
  SR040, plus SR002 if config-driven regex turns out insufficient),
  refactor hints, scoring, and PR-level checks.

[^sr020]: `StaticConditionCheck` is graded **error** uniformly: a literal-equals-literal sub-expression like `1 = 1` is wrong regardless of what surrounds it — `and x` doesn't redeem it, it just hides leftover debug code. Bare `if (x)` is *not* flagged because it is the idiomatic null/truthy check in this language.

[^sr012_1]: SR012.1 counts `//` and `/* ... */` comments from `CheckContext.comments` (tokenizer side-channel) and complexity from `_count_complexity` (shared with SR091). The 1:12 ratio targets non-obvious code: assignments don't need comments, but branches and risky calls usually do.

[^sr031]: `NestedLoopCheck` grades severity by bound-ness and side-effects: **info** when both loops are provably bounded by literal counters, **error** when the inner body contains an expensive call (SQL, service, object lookup, or any method call), **warning** otherwise.

[^sr032]: `RepeatedQueryCheck` grades severity by similarity tier across both query primitives (`getSqlData`, `getData`): **error (T1)** for exact duplicate queries (same table, SELECT, WHERE); **warning (T2)** for same table + WHERE with different SELECT fields (suggested fix: union the SELECT); **info (T3)** for same table + SELECT whose WHEREs differ only in exactly one column's literal-equality value (suggested fix: merge with `column IN (val1, val2)`). The check sees flattened SQL strings — string-concatenation builders and one-shot variable assignments are resolved before comparison.

[^sr091]: `TooFewLogsCheck` fires when **stmts > 50** AND **log_calls × 5 < complexity**, where complexity = branches + loops + risky calls. The 1-log-per-5-constructs ratio is conservative — most rules pass; only the genuinely under-instrumented ones fire. A long but straight-line script (no branches, no risky calls) needs no logs and is silent.

[^sr044]: Reuses `_sql.py`'s query-flattening helper to share a "literal vs dynamic" classification with SR030 and SR032. A query is considered literal if it's a `StringLit` or a concatenation of `StringLit`s and identifier substitutions only. Anything else (unflattenable expression, computed at runtime) is dynamic and fires.

[^sr062]: Valid TRIGGER_TYPE integer values per `schema.xml`'s `RULE_TRIGGER_TYPE` simple type are: 10, 11, 12, 13, 14, 20, 21, 30, 31, 40, 50, 51, 60. Anything outside this set fires.

[^sr043]: Deferred pending review of real-world BizRule contexts where missing try/onerror is genuinely problematic. The blanket form (every risky call must be wrapped) is too noisy for this codebase.

[^sr033]: `UnboundedLoopCheck` visits `WhileStmt`, `DoWhile`, and `ForCStyle` only — `foreach` and counter-`for` are bounded by language design. Two firing paths: (1) **trivial-infinite** when the condition is a non-zero `NumberLit` or non-empty `StringLit` (or a C-style `for` with no condition); (2) **unbounded condition** when the set of identifier / field-access string-forms in the condition is disjoint from the set of `AssignStmt` targets in the body (and in the C-for step). Function and method calls in the body do *not* count as mutations — only `:=` and `?=` mutate. Function and method *names* in callee position are not collected as condition variables either. A condition with no extractable identifiers (e.g. `while (getStatus())`) is silent: no signal to reason about.

[^sr059]: `UnusedVariableCheck` walks each script once collecting (a) the first-line of every `AssignStmt` whose target is a bare `Identifier`, and (b) the set of `Identifier` names appearing in read positions. Counter-`for` and `foreach` loop variables are excluded from both sets — loop-introduced names are idiomatic to ignore. Function/method *names* in callee position are not reads; method *receivers* are. `?=` is treated as an assignment with no read semantics (purely an assign for SR059 purposes). Multiple assignments to the same name collapse onto the first one's line in the finding. Severity is `info`.

## 9. Open questions
- Is there an authoritative list of valid object / class names the reviewer
  can use for SR050/SR061 (dependency existence)?
- What defines "previous version" for SR08x — previous git commit, previous
  pack on disk, or a versioned store?
