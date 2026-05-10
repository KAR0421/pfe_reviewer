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
stable; pick the next free ID when adding a new check. Status is one of
`done`, `pending`, or `agentic` (deferred to the LLM-driven phase).

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
| SR011   | warning  | Missing or empty `DESCRIPTION`. | pending |
| SR012.1 | warning  | Insufficient inline comment density: fewer than 1 `//` comment per 12 branches/loops/risky calls. Complexity definition same as SR091 (branches + loops + risky_calls). [^sr012_1] | done |
| SR012.2 | info     | Comments describe *how* instead of *why*. | agentic |

#### Static logic
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR020 | error    | Condition is always true / always false (two literals, same var both sides, or a literal-vs-literal sub-expression hidden inside `and`/`or`). [^sr020] | done |
| SR021 | warning  | Dead code after `return` / `abort` / `skip`. | done |
| SR022 | info     | Pre-conditions placed after computations (suboptimal ordering). | pending |

#### Basic performance
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR030 | error    | SQL query (`getSqlData`) executed inside a loop. | done |
| SR031 | warning  | Nested loops (two or more levels). [^sr031] | done |
| SR032 | warning  | Duplicate / near-duplicate queries in the same rule. [^sr032] | done |
| SR033 | warning  | Unbounded or trivially infinite loop. | pending |
| SR034 | info     | Repeated read of the same object field without local caching. | pending |

#### Security & robustness
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR040 | error    | Hardcoded sensitive literal (credential, URL, ID looking like a secret). | agentic |
| SR041 | error    | Division where the right operand could be zero. | pending |
| SR042 | warning  | Field access on a value not checked for null / existence. Note: `obj.FIELD[COND] := v` auto-creates if no record matches — treat this as a different class of issue, not a null guard failure. | pending |
| SR043 | warning  | Risky call (`getSqlData`, `callService`, `getObjects`, `obj.set`, `obj.method(...)`) not wrapped in a `try { } onerror { }` block. | pending |

#### Dependencies
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR050 | error    | BizRule / class / list referenced but not in the pack or the reference. | pending |
| SR051 | warning  | Cross-dependency (BR A calls BR B which calls A). | pending |
| SR052 | info     | BizRule references an object that exists only partially (e.g. missing field). | pending |

#### Language semantics (revealed by `syntaxe.odt`)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR055 | warning  | Array alias: `b := a` between array-typed variables with no subsequent `arraycopy` — mutations to `b` will affect `a`. | pending |
| SR056 | info     | `:=` used where `?=` may have been intended (or vice versa). Heuristic — flag as info only. | pending |
| SR057 | info     | Variables in the same rule differing only in case (e.g. `contrib` and `Contrib`) — likely typo since names are case-sensitive. | pending |
| SR058 | info     | Unintended record auto-create: assignment to `obj.FIELD[COND] := v` without an existence check first. The kernel silently creates a record when none matches. | pending |

### Should Have — if time permits

#### Scope (technical)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR060 | warning  | `SMARTRULE_TRIGGER` empty or malformed. | pending |
| SR061 | warning  | `TRIGGER_OBJECT` not present in the reference or the pack. | pending |
| SR062 | info     | `TRIGGER_TYPE` code does not match a known enum value. | pending |

#### Return-type usage
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR070 | info     | Return type of a called BizRule cannot be inferred. | pending |
| SR071 | warning  | Return value of a called BizRule is ignored. | pending |
| SR072 | warning  | Return value is used inconsistently with its declared type. | pending |

#### Version comparison
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR080 | info     | Rule has changed vs. previous version. | pending |
| SR081 | warning  | Logic change detected (not just whitespace / comments). | pending |
| SR082 | error    | Possible involuntary overwrite of a newer version. | pending |

#### Logs
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR090 | warning  | Verbose log call inside a loop. | done |
| SR091 | info     | Long script with insufficient log density relative to its branching / loop / risky-call complexity. [^sr091] | done |
| SR092 | info     | Log call emits only a constant string (no key values). | pending |

### Nice to Have — bonus
- **AI / ML pattern detection** — flag known-risky constructs via a
  trained classifier. No rule IDs assigned yet.
- **Refactoring hints** — propose *hints* only (complexity hotspots,
  repeated blocks worth extracting). Do not generate replacement code.
- **Advanced scoring** — global score (0–100), per-category sub-scores,
  `merge safe / risky` indicator.

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

- **M1 — done.** AST pipeline shipped: tokenizer, parser, engine, nine
  checks (SR010, SR012.1, SR020, SR021, SR030, SR031, SR032, SR090,
  SR091), full test suite green.
- **M2 — current.** Finish the remaining structural Must-Have checks
  (SR011, SR022, SR033, SR034, SR041–SR043, SR050–SR052, SR055–SR058,
  plus SR002).
- **M3 — Bitbucket integration.** Post findings as PR comments via the
  Bitbucket REST API; CI hook.
- **M4 — Should-Have checks.** DB-connected dependency resolution
  (SR050/SR061), return-type checks (SR070–SR072), version diff
  (SR080–SR082), log polish (SR092).
- **M5 — Agentic checks and quality.** LLM-driven checks for the
  semantic patterns marked `agentic` above (SR001, SR003, SR012.2,
  SR040), plus refactor hints, scoring, and PR-level checks.

[^sr020]: `StaticConditionCheck` is graded **error** uniformly: a literal-equals-literal sub-expression like `1 = 1` is wrong regardless of what surrounds it — `and x` doesn't redeem it, it just hides leftover debug code. Bare `if (x)` is *not* flagged because it is the idiomatic null/truthy check in this language.

[^sr012_1]: SR012.1 counts `//` and `/* ... */` comments from `CheckContext.comments` (tokenizer side-channel) and complexity from `_count_complexity` (shared with SR091). The 1:12 ratio targets non-obvious code: assignments don't need comments, but branches and risky calls usually do.

[^sr031]: `NestedLoopCheck` grades severity by bound-ness and side-effects: **info** when both loops are provably bounded by literal counters, **error** when the inner body contains an expensive call (SQL, service, object lookup, or any method call), **warning** otherwise.

[^sr032]: `RepeatedQueryCheck` grades severity by similarity tier across both query primitives (`getSqlData`, `getData`): **error (T1)** for exact duplicate queries (same table, SELECT, WHERE); **warning (T2)** for same table + WHERE with different SELECT fields (suggested fix: union the SELECT); **info (T3)** for same table + SELECT whose WHEREs differ only in exactly one column's literal-equality value (suggested fix: merge with `column IN (val1, val2)`). The check sees flattened SQL strings — string-concatenation builders and one-shot variable assignments are resolved before comparison.

[^sr091]: `TooFewLogsCheck` fires when **stmts > 50** AND **log_calls × 5 < complexity**, where complexity = branches + loops + risky calls. The 1-log-per-5-constructs ratio is conservative — most rules pass; only the genuinely under-instrumented ones fire. A long but straight-line script (no branches, no risky calls) needs no logs and is silent.

## 9. Open questions
- Is there an authoritative list of valid object / class names the reviewer
  can use for SR050/SR061 (dependency existence)?
- Which enum values of `TRIGGER_TYPE` matter for SR062?
- For SR040 (hardcoded sensitive literals), do we have a regex catalogue
  from security, or do we write our own?
- What defines "previous version" for SR08x — previous git commit, previous
  pack on disk, or a versioned store?
