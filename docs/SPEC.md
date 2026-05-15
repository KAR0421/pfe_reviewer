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
| SR002 | warning  | BizRule `RULE_CODE` does not follow project naming convention. [^sr002] | done |
| SR003 | info     | Rule name / code mismatch with its documented purpose. | agentic |

#### Minimal documentation
| ID      | Severity | Description | Status |
|---------|----------|-------------|--------|
| SR010   | error    | Missing or empty `USER_COMMENT`. | done |
| SR011   | warning  | Missing SMARTRULE_NAME: the rule has no display name in any language. Lenient — at least one language is enough. | done |
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
| SR034 | info     | Repeated reads of the same field on the same object without intervening reassignment (e.g. `x := obj.F; y := obj.F;` — caching `obj.F` once would be cleaner). [^sr034] | done |

#### Security & robustness
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR040 | error    | Hardcoded business-sensitive literal (ID, threshold, name, label, file path, magic number). An agent reviews each non-trivial literal in context to decide whether it should be parameterized. | agentic |
| SR041 | error    | Division where the right operand could be zero. [^sr041] | done |
| SR042 | warning  | Field access on a value that has not been guarded against null or empty. The check tracks both `if (obj != null) { ...obj.F... }` (then-branch guard) and `if (obj = null) { ... } else { ...obj.F... }` (else-branch guard) — guard tracking is structural via the engine's branch awareness. | pending |
| SR043 | warning  | Risky call (`getSqlData`, `callService`, `getObjects`, `obj.set`, `obj.method(...)`) not wrapped in a `try { } onerror { }` block. [^sr043] | should-have |

#### Dependencies
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR051 | warning  | Cross-dependency (BR A calls BR B which calls A). | pending |
| SR052 | info     | BizRule references an object that exists only partially (e.g. missing field). | pending |

#### Language semantics (revealed by `syntaxe.odt`)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR055 | warning  | Array alias: `b := a` between array-typed variables with no subsequent `arraycopy` — mutations to `b` will affect `a`. [^sr055] | done |
| SR057 | info     | Variables in the same rule differing only in case (e.g. `contrib` and `Contrib`) — likely typo since names are case-sensitive. [^sr057] | done |
| SR058 | warning  | Unintended record auto-create: assignment to `obj.FIELD[COND] := v` without an enclosing existence check on the same selector. The kernel silently creates a row when none matches. [^sr058] | done |
| SR059 | info     | Unused variable: assigned (`x := 1`) but never read. [^sr059] | done |

#### Scope (technical)
| ID    | Severity | Description | Status |
|-------|----------|-------------|--------|
| SR060 | warning  | `SMARTRULE_TRIGGER` missing entirely, or a trigger of an *object-required* type (20, 21, 30, 31, 40, 41 — record/field events) has an empty `TRIGGER_OBJECT`. Object-not-required types (10–14, 50, 51) are silent; type 60 is SR061's territory. [^sr060] | done |
| SR061 | warning  | `TRIGGER_TYPE=60` (internal process) on a rule requires at least one of its type-60 triggers to have `TRIGGER_OBJECT` equal to the rule's own `RULE_CODE`. Other type-60 triggers in the same rule may reference any `RULE_CODE` (in or out of the pack) — chaining to external rules is a valid pattern. [^sr061] | done |
| SR062 | info     | `TRIGGER_TYPE` code does not match a known enum value. [^sr062] | done |

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

1. SR042 — guarded field access (flow analysis)

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

- **M1 — done.** AST pipeline shipped: tokenizer, parser, engine, twenty-three
  checks (SR002, SR010, SR011, SR012.1, SR020, SR021, SR030, SR031, SR032,
  SR033, SR034, SR041, SR055, SR057, SR058, SR059, SR060, SR061, SR062,
  SR090, SR091, SR093, SR094), full test suite green.
- **M2 — current.** Finish the remaining structural Must-Have checks
  in the order documented in §6 "M2 build order" (SR042).
- **M3 — Bitbucket integration.** Post findings as PR comments via the
  Bitbucket REST API; CI hook.
- **M4 — DB-connected and harder checks.** SR043 (after redefining
  which contexts warrant the warning), SR050, SR051, SR052, the
  DB-connected variant of SR061, return-type checks (SR070–SR072),
  version diff (SR080–SR082), SR022 (promoted out of M2), and SR092.
- **M5 — Agentic checks and quality.** LLM-driven checks for the
  semantic patterns marked `agentic` in §6 (SR001, SR003, SR012.2,
  SR040, plus SR002 if the static regex turns out insufficient),
  refactor hints, scoring, and PR-level checks.

[^sr020]: `StaticConditionCheck` is graded **error** uniformly: a literal-equals-literal sub-expression like `1 = 1` is wrong regardless of what surrounds it — `and x` doesn't redeem it, it just hides leftover debug code. Bare `if (x)` is *not* flagged because it is the idiomatic null/truthy check in this language.

[^sr002]: `RuleCodeNamingCheck` enforces the regex `^[A-Z][A-Z0-9_]{2,}$` on `BizRule.name` (the `RULE_CODE`). Concretely: the first character must be an uppercase ASCII letter; remaining characters may be uppercase letters, digits, or underscores; minimum total length is 3. Real production codes (`UPDATE_DOCUMENT_PROCESS`, `TRANSCO_NPC23`, `COMPUTE_TEMPLATE_ORDER`) all match. Common defects all fail: lowercase (`myRule`), leading digit (`1_RULE`), hyphen or other punctuation (`RULE-X`), whitespace (`RULE NAME`), and stub names too short to be meaningful (`RU`). The check is BizRule-level (overrides `visit_BizRule`) and emits with `line=0` because the offending location is the rule's metadata, not any line of the script. The pattern lives as a module-level constant `RULE_CODE_PATTERN` in `metadata.py` so a future config-driven variant (see M5) can swap it out cleanly.

[^sr055]: `ArrayAliasCheck` recognises array-typed variables by tracking which locals are assigned from a call to one of the array-returning built-ins: `array`, `arraycopy`, `arrayappend`, `arrayremove`, `arrayunion`, `arraysubset`, `arraysubfind`, `arraysort`. `arraysize` is **not** in this set — it returns the integer length, not an array, so `n := arraysize(a)` does not tag `n`. Once a variable is array-typed, a bare-Identifier-to-bare-Identifier assignment `b := a` (RHS *not* wrapped in `arraycopy(...)`) is recorded as a candidate alias and `b` becomes array-typed too, supporting transitive chains like `a := array(...); b := arrayremove(a, 1); c := b`. After the source-order walk, each candidate `(b, a, alias_line)` is gated by a "later mutation" check: at least one source line strictly greater than `alias_line` must re-assign or indexed-write either side (`b := …`, `a[i] := …`). Aliases without a later mutation may be a deliberate second name for the same array, so they stay silent. Field/`TableSelector` writes never participate in aliasing; counter-`for` and `foreach` loop-introduced names are excluded from both sides; the `arraycopy(...)` form is the documented correct pattern and is silent by construction.

[^sr041]: `DivByZeroCheck` visits every `BinaryOp` whose `op` is `"/"` and grades into three buckets via the helper `classify_numeric_guard` in `_guards.py`, which walks the engine's `if_stack` from innermost outward and returns the first non-`None` verdict. **error (`KNOWN_ZERO`)**: literal `Y / 0`, or the divisor is provably zero in the current branch — `if (Y = 0) { … Y … }` (then), `if (Y != 0) { } else { … Y … }` (else), `if (not(Y)) { … Y … }` (then), `if (Y) { } else { … Y … }` (else). **silent (`KNOWN_NONZERO`)**: literal non-zero divisor; or the guard proves non-zero — `Y != 0` (then), `Y > 0` (then), `Y < 0` (then), `Y >= N` with literal `N > 0`, `Y <= N` with literal `N < 0`, bare-truthy `Y`, value-engagement equality such as `Y = "ACTIVE"` or `Y = 5`. **warning (`UNKNOWN`)**: no enclosing frame mentions the divisor, or the only frames that do mention it use guards that don't establish either side (`Y >= 0` admits zero; `Y != someVar` doesn't establish anything). Function-call divisors (`x := total / func()`) are conservatively skipped — the check cannot reason about return values. Compound conditions (`and` / `or`) currently short-circuit to `UNKNOWN`; refine if real packs need it. Magnitude-comparison precision (`>` / `<` / `>=` / `<=` against a numeric literal) is the new logic that distinguishes this check from the SR058-style classifier — `Y >= 1` excludes zero but `Y >= 0` does not.

[^sr012_1]: SR012.1 counts `//` and `/* ... */` comments from `CheckContext.comments` (tokenizer side-channel) and complexity from `_count_complexity` (shared with SR091). The 1:12 ratio targets non-obvious code: assignments don't need comments, but branches and risky calls usually do.

[^sr031]: `NestedLoopCheck` grades severity by bound-ness and side-effects: **info** when both loops are provably bounded by literal counters, **error** when the inner body contains an expensive call (SQL, service, object lookup, or any method call), **warning** otherwise.

[^sr032]: `RepeatedQueryCheck` grades severity by similarity tier across both query primitives (`getSqlData`, `getData`): **error (T1)** for exact duplicate queries (same table, SELECT, WHERE); **warning (T2)** for same table + WHERE with different SELECT fields (suggested fix: union the SELECT); **info (T3)** for same table + SELECT whose WHEREs differ only in exactly one column's literal-equality value (suggested fix: merge with `column IN (val1, val2)`). The check sees flattened SQL strings — string-concatenation builders and one-shot variable assignments are resolved before comparison.

[^sr091]: `TooFewLogsCheck` fires when **stmts > 50** AND **log_calls × 5 < complexity**, where complexity = branches + loops + risky calls. The 1-log-per-5-constructs ratio is conservative — most rules pass; only the genuinely under-instrumented ones fire. A long but straight-line script (no branches, no risky calls) needs no logs and is silent.

[^sr057]: `CaseTypoVariableCheck` fires only when **at least one** of the case-variant spellings is a real assigned variable in the rule (bare-`Identifier` `:=` / `?=` target, not field/index assignment, not loop-introduced). When *neither* spelling is assigned, both are almost certainly external constants / enums / functions and out of scope. Identifiers in `Call.callee` position (function names) are excluded from occurrences. Identifiers on the LHS of a comparison operator (`=`, `!=`, `<`, `>`, `<=`, `>=`) inside a `TableSelector.condition` are treated as column names from the data model, not variables, and are excluded from occurrence collection — the same column-context rule is also applied by SR059's collector.

[^sr062]: Valid TRIGGER_TYPE integer values per `schema.xml`'s `RULE_TRIGGER_TYPE` simple type are: 10, 11, 12, 13, 14, 20, 21, 30, 31, 40, 50, 51, 60. Anything outside this set fires.

[^sr060]: Trigger types split into two groups by whether `TRIGGER_OBJECT` is required to name a target field/record. **Object-required (this check):** 20 = record created, 21 = record to be deleted, 30 = field to be indirectly changed, 31 = field indirectly changed, 40 = field to be changed, 41 = field changed. An empty `TRIGGER_OBJECT` on these types is a misconfiguration — the trigger has no target. **Object-not-required (silent):** 10–14, 50, 51 — these fire globally; an empty `TRIGGER_OBJECT` is valid. **Type 60** (internal process) also requires `TRIGGER_OBJECT` but with different semantics (must reference a `RULE_CODE`, not a field) and is owned by SR061 to avoid double-flagging. The pre-correction check fired on *any* empty `TRIGGER_OBJECT` regardless of type and produced false positives on real production data (`UPDATE_DOCUMENT_PROCESS` uses type 13, which doesn't require an object).

[^sr061]: Type 60 (internal process) is the dispatch mechanism by which one BizRule explicitly invokes another by `RULE_CODE`. The structural invariant SR061 enforces is the **self-reference invariant**: if a rule has any type-60 trigger, at least one of those triggers' `TRIGGER_OBJECT` must equal the rule's own `RULE_CODE`. Otherwise the rule advertises an entry point that nothing connects to itself, and the platform cannot invoke it via internal-process dispatch. Fired at most once per rule, regardless of how many type-60 triggers exist (category `scope` — structural). Other type-60 triggers in the same rule may reference any `RULE_CODE`, in or out of the pack: chaining to an external rule is a legitimate pattern and is **not** flagged. Earlier drafts of this check also performed per-trigger intra-pack resolution and flagged empty type-60 `TRIGGER_OBJECT` values; both behaviors were removed because they over-flagged valid chaining configurations.

[^sr043]: Deferred pending review of real-world BizRule contexts where missing try/onerror is genuinely problematic. The blanket form (every risky call must be wrapped) is too noisy for this codebase.

[^sr033]: `UnboundedLoopCheck` visits `WhileStmt`, `DoWhile`, and `ForCStyle` only — `foreach` and counter-`for` are bounded by language design. Two firing paths: (1) **trivial-infinite** when the condition is a non-zero `NumberLit` or non-empty `StringLit` (or a C-style `for` with no condition); (2) **unbounded condition** when the set of identifier / field-access string-forms in the condition is disjoint from the set of `AssignStmt` targets in the body (and in the C-for step). Function and method calls in the body do *not* count as mutations — only `:=` and `?=` mutate. Function and method *names* in callee position are not collected as condition variables either. A condition with no extractable identifiers (e.g. `while (getStatus())`) is silent: no signal to reason about.

[^sr059]: `UnusedVariableCheck` walks each script once collecting (a) the first-line of every `AssignStmt` whose target is a bare `Identifier`, and (b) the set of `Identifier` names appearing in read positions. Counter-`for` and `foreach` loop variables are excluded from both sets — loop-introduced names are idiomatic to ignore. Function/method *names* in callee position are not reads; method *receivers* are. `?=` is treated as an assignment with no read semantics (purely an assign for SR059 purposes). Multiple assignments to the same name collapse onto the first one's line in the finding. Severity is `info`.

[^sr034]: `RepeatedFieldReadCheck` uses a structural-identity key `(target_dotted_name, field)` for every `FieldAccess` whose `target` is a bare `Identifier` or a chain of `FieldAccess` rooted at one (helper `dotted_name` in `_field_access.py`). Forms like `getThing().F` are skipped — no stable source variable to use as a cache key. **Method-call callees are excluded**: a `FieldAccess` appearing in `Call.callee` position is not counted as a read, because `obj.method()` may have side effects or return different values per invocation, so two such calls aren't redundant the way two reads of `obj.F` are (same exclusion as SR057/SR059); the receiver chain (e.g. `obj.sub` inside `obj.sub.method()`) is still walked for nested reads. Detection is event-based, walking the script in source order: `read(key)` events (every qualifying `FieldAccess`), `var_assign(name)` events (any `AssignStmt` whose target is a bare `Identifier`, invalidates every cached group whose root equals `name`), and `field_assign(key)` events (any `AssignStmt` whose target is a `FieldAccess`, invalidates that specific key). Within a single statement, value-side reads are emitted before the target-side write so `obj.F := obj.F + 1` does not self-invalidate. Reads of the same key accumulate into a *group*; a group is closed by an invalidating event or at end-of-script and, if it contains N≥2 reads, produces **exactly one** finding anchored at the first read's line, with a message listing all N read lines and the total count (e.g. `"Field 'obj.F' read 3 times (lines 1, 2, 3) — consider caching in a local variable to avoid repeated lookups."`). Severity is `info` — these are caching hints, not defects.

[^sr058]: `AutoCreateAssignCheck` fires on `AssignStmt` whose target is a `TableSelector` and whose enclosing if-stack does not contain a *relevant* existence check. Relevance is decided by walking the engine's `if_stack` from innermost outward; the first `IfFrame` whose condition references the same `TableSelector` (structural equality on target/field/condition, helper `tableselector_structural_eq` in `_guards.py`) decides the verdict. Comparison shapes are classified by `classify_comparison` into three buckets: **EMPTINESS_CHECK** (`TS = null`, `TS = ""`, `not(TS)` — true exactly when the row is missing; firing in the then-branch, silent in else), **PRESENCE_CHECK** (`TS != null`, `TS != ""`, bare `TS` — true exactly when the row is present; silent in then, firing in else), or **VALUE_ENGAGEMENT** (any other comparison referencing the value: `TS = "VALIDATED"`, `TS > 5`, `TS != someVar`, … — the developer reads the value's content, implicitly asserting presence; safe in either branch). Boolean combinators (`and`/`or`) recurse and return the strongest classification (VALUE_ENGAGEMENT > PRESENCE > EMPTINESS), where "strongest" = "most likely to keep the assignment silent" — adding extra clauses to a guard shouldn't *create* a finding that a simpler guard wouldn't have produced. The language has no `!` token; logical negation is the built-in `not(...)` call. Both quote styles for empty strings (`""` and `''`) count.

## 9. Open questions
- Is there an authoritative list of valid object / class names the reviewer
  can use for SR050/SR061 (dependency existence)?
- What defines "previous version" for SR08x — previous git commit, previous
  pack on disk, or a versioned store?
