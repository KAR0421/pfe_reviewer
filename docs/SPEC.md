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

## 2. Goal
Build a tool that:
1. **Extracts** BizRules from XML pack files.
2. **Analyzes** the scripts against a fixed scope of quality checks.
3. **Emits** a structured report of findings.
4. (Later) **Integrates** with Bitbucket pull requests to post the report
   as inline comments.

## 3. Non-goals
- Rewriting or auto-fixing scripts (the team explicitly wants no
  solution suggestions — only detection and optional refactor *hints*).
- Executing or simulating scripts dynamically.
- Parsing or validating non-BizRule objects in the pack (classes, lists) —
  except insofar as they are referenced by BizRules for dependency checks.
- Replacing the NeoXam editor or the product itself.

## 4. Architecture
```
┌────────────┐   ┌─────────┐   ┌────────────┐   ┌──────────┐   ┌────────┐
│ .pack XML  │→ │ Parser  │→ │ BizRule[]  │→ │ Reviewer │→ │ Report │
└────────────┘   └─────────┘   └────────────┘   └──────────┘   └────────┘
                                                                    │
                                                        later: ┌────┴─────┐
                                                               │ Bitbucket│
                                                               │ comments │
                                                               └──────────┘
```
Modules:
- `parser.py`       — regex extraction of `<SMARTRULE>` blocks.
- `xml_loader.py`   — alternative sanitize-then-parse loader.
- `preprocessor.py` — line-level normalization (currently minimal).
- `reviewer.py`     — `check_*` functions + orchestrator `review_bizrule`.
- `main.py`         — CLI entry point.

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

Reporting: today, `review_bizrule` returns `{"name": str, "issues": list[str]}`.
Target:
```python
@dataclass
class Finding:
    rule_id: str     # "SR###"
    category: str    # naming|docs|logic|perf|security|deps|logs|scope
    severity: str    # info|warning|error
    line: int | None
    message: str

@dataclass
class Report:
    rule_name: str
    findings: list[Finding]
    score: int | None   # 0..100, added in "Nice to Have" phase
```

## 6. Review scope
Translated and expanded from `docs/review-scope.pdf`. Rule IDs are
stable; pick the next free ID when adding a new check.

### Must Have — automated, mandatory

#### Naming & conventions
| ID    | Severity | Description |
|-------|----------|-------------|
| SR001 | warning  | Generic / ambiguous variable names (`tmp1`, `varX`, `temp`). |
| SR002 | warning  | BizRule `RULE_CODE` does not follow project naming convention. |
| SR003 | info     | Rule name / code mismatch with its documented purpose. |

#### Minimal documentation
| ID    | Severity | Description |
|-------|----------|-------------|
| SR010 | error    | Missing or empty `USER_COMMENT`. |
| SR011 | warning  | Missing or empty `DESCRIPTION`. |
| SR012 | info     | Comments describe *how* instead of *why*. |

#### Static logic
| ID    | Severity | Description |
|-------|----------|-------------|
| SR020 | warning  | Condition is always true / always false (two literals, same var both sides). |
| SR021 | warning  | Dead code after `return` / `abort` / `skip`. |
| SR022 | info     | Pre-conditions placed after computations (suboptimal ordering). |

#### Basic performance
| ID    | Severity | Description |
|-------|----------|-------------|
| SR030 | error    | SQL query (`getSqlData`) executed inside a loop. |
| SR031 | warning  | Nested loops (two or more levels). |
| SR032 | warning  | Duplicate / near-duplicate queries in the same rule. |
| SR033 | warning  | Unbounded or trivially infinite loop. |
| SR034 | info     | Repeated read of the same object field without local caching. |

#### Security & robustness
| ID    | Severity | Description |
|-------|----------|-------------|
| SR040 | error    | Hardcoded sensitive literal (credential, URL, ID looking like a secret). |
| SR041 | error    | Division where the right operand could be zero. |
| SR042 | warning  | Field access on a value not checked for null / existence. Note: `obj.FIELD[COND] := v` auto-creates if no record matches — treat this as a different class of issue, not a null guard failure. |
| SR043 | warning  | Risky call (`getSqlData`, `callService`, `getObjects`, `obj.set`, `obj.method(...)`) not wrapped in a `try { } onerror { }` block. |

#### Dependencies
| ID    | Severity | Description |
|-------|----------|-------------|
| SR050 | error    | BizRule / class / list referenced but not in the pack or the reference. |
| SR051 | warning  | Cross-dependency (BR A calls BR B which calls A). |
| SR052 | info     | BizRule references an object that exists only partially (e.g. missing field). |

#### Language semantics (revealed by `syntaxe.odt`)
| ID    | Severity | Description |
|-------|----------|-------------|
| SR055 | warning  | Array alias: `b := a` between array-typed variables with no subsequent `arraycopy` — mutations to `b` will affect `a`. |
| SR056 | info     | `:=` used where `?=` may have been intended (or vice versa). Heuristic — flag as info only. |
| SR057 | info     | Variables in the same rule differing only in case (e.g. `contrib` and `Contrib`) — likely typo since names are case-sensitive. |
| SR058 | info     | Unintended record auto-create: assignment to `obj.FIELD[COND] := v` without an existence check first. The kernel silently creates a record when none matches. |

### Should Have — if time permits

#### Scope (technical)
| ID    | Severity | Description |
|-------|----------|-------------|
| SR060 | warning  | `SMARTRULE_TRIGGER` empty or malformed. |
| SR061 | warning  | `TRIGGER_OBJECT` not present in the reference or the pack. |
| SR062 | info     | `TRIGGER_TYPE` code does not match a known enum value. |

#### Return-type usage
| ID    | Severity | Description |
|-------|----------|-------------|
| SR070 | info     | Return type of a called BizRule cannot be inferred. |
| SR071 | warning  | Return value of a called BizRule is ignored. |
| SR072 | warning  | Return value is used inconsistently with its declared type. |

#### Version comparison
| ID    | Severity | Description |
|-------|----------|-------------|
| SR080 | info     | Rule has changed vs. previous version. |
| SR081 | warning  | Logic change detected (not just whitespace / comments). |
| SR082 | error    | Possible involuntary overwrite of a newer version. |

#### Logs
| ID    | Severity | Description |
|-------|----------|-------------|
| SR090 | warning  | Verbose log call inside a loop. |
| SR091 | info     | Long script (>50 lines) with fewer than 3 log calls. |
| SR092 | info     | Log call emits only a constant string (no key values). |

### Nice to Have — bonus
- **AI / ML pattern detection** — flag known-risky constructs via a
  trained classifier. No rule IDs assigned yet.
- **Refactoring hints** — propose *hints* only (complexity hotspots,
  repeated blocks worth extracting). Do not generate replacement code.
- **Advanced scoring** — global score (0–100), per-category sub-scores,
  `merge safe / risky` indicator.

## 7. Output
### Phase 1 — console (current)
Text block per BizRule; numbered list of issues; `"No issues found!"` when clean.

### Phase 2 — structured
JSON matching the `Report` dataclass above, one object per rule, dumped to
stdout or a file.

### Phase 3 — Bitbucket integration
Post findings as inline PR comments, one per finding at its line number.
Requires: Bitbucket REST API credentials, a mapping from pack file + line
to the PR diff, and a batch-comment strategy (probably one summary comment
+ inline for `severity >= warning`).

## 8. Milestones
1. **M1 — Foundation (current).** Parser + reviewer running against a pack
   from disk; 8 Must-Have checks; console output.
2. **M2 — Harden.** Finding dataclass, rule IDs, JSON output, test suite,
   remaining Must-Have checks (security, dependencies).
3. **M3 — Should Have.** Trigger/scope checks, log quality, version diff.
4. **M4 — Integration.** Bitbucket PR comments, CI hook.
5. **M5 — Nice to Have.** Scoring, refactor hints, ML prototype.

## 9. Open questions
- Is there an authoritative list of valid object / class names the reviewer
  can use for SR050/SR061 (dependency existence)?
- Which enum values of `TRIGGER_TYPE` matter for SR062?
- For SR040 (hardcoded sensitive literals), do we have a regex catalogue
  from security, or do we write our own?
- What defines "previous version" for SR08x — previous git commit, previous
  pack on disk, or a versioned store?
- ~~Does the language have try/catch?~~ **Answered (`syntaxe.odt`):** yes —
  `try { } onerror { }`, with an implicit typed `error` variable. SR043
  now checks for it.
