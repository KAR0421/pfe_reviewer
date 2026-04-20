---
name: "BizRule Script Syntax"
description: "Syntax of the NeoXam-style scripting language this tool reviews"
applyTo: "reviewer.py,preprocessor.py,reviewer/**,tests/fixtures/**,**/*.smartrule"
---

# BizRule scripting language — quick reference

Scripts live inside `<IMPACT>` CDATA blocks of `<SMARTRULE>` elements.
This is a proprietary DSL — treat it as such. The full authoritative reference
is in `docs/scripting-grammar.md`; the essentials for writing review checks
follow.

## Lexical
- **Assignment:** `:=` (plain) or `?=` (assigns only if variable is empty).
- **Equality:**   `=` (NOT `==`).
- **Inequality:** `!=`.
- **Relational:** `<`, `<=`, `>`, `>=`.
- **Logical:**    `and`, `or`.
- **Comments:**   `// line comment` (no block comments).
- **Statement terminator:** `;`.
- **Strings:**    `"..."` or `'...'`. Concatenation with `+`.
- **Falsy values:** `0` and `""` (no `true`/`false` keywords).
- **Case sensitivity:** variable names are case-sensitive; function names
  are NOT.

## Control flow
```
if (cond) { ... }
if (cond) stmt else stmt                 // one-liner form, common
for (init; cond; step) { ... }
for var := n to   m do { ... }
for var := n downto m do { ... }
foreach v in iterable do { ... }
foreach obj.TABLE do { ... }             // walks a table via object cursor
while (cond) { ... }
do { ... } while (cond);
```
Every loop body may be a single statement — do NOT assume braces.

## Terminators
- `return;` / `return expr;`  — exits the rule
- `abort [expr]`              — aborts with error
- `skip [expr]`               — skip current iteration

Anything non-empty after one of these (before the next `}` or the end of
the branch) is **dead code**.

## Error handling
```
try { ... }
onerror {
    if (error.isType("dqc")) { ... }
}
```
`try` must be immediately followed by `onerror`. Inside `onerror`, the
implicit `error` variable (type `ScriptError`) has `.isType("...")`.
Error types: `dqc`, `integrity`, `abort`, `script`, `internal`, `server`,
`dictionary`.

## Objects and table cursors
- Field access: `obj.FIELD`.
- Each object variable holds a **cursor per table** — assigning to a new
  variable (`copy := obj`) gives it independent cursors.
- Row selection: `obj.FIELD[KEY = "X" and OTHER = 1]`
  — only `=` and `and` allowed in the condition.
- Assignment via that syntax with no matching record → **new record is
  created** (auto-create semantic; flag surprise creates).

## Arrays (⚠️ reference semantics)
```
a := array();                // build empty
arraysize(a); a[0]; arrayappend(a, v);
b := a;                      // b IS a — NOT a copy
c := arraycopy(a);           // independent copy
```
`b := a` between two array-typed variables without an intervening
`arraycopy` is a footgun worth flagging.

## Implicit variables by execution context
| Context                       | Implicit vars                              |
|-------------------------------|--------------------------------------------|
| Trigger on object mod         | `obj`, `newvalue`                          |
| Action on mono-object         | `obj`                                      |
| Action on multi-object        | `objects` (array), sometimes `objectset`   |
| Action on a pool              | `master_object`, `obj1`, `objectset`       |
| User-defined method           | `obj`, `arg1`…`argN`, `argcount`           |
| User-defined function         | `arg1`…`argN`, `argcount`                  |

`obj1` is context-dependent (pool rule ≠ method caller). Do not assume one
meaning; look at the trigger type in `SMARTRULE_TRIGGER` when needed.

## Built-ins the reviewer already knows about
- Logging: `msginfo`, `msgerror`, `msgwarn`
- Arrays: `array`, `arraysize`, `arraycopy`, `arrayappend`, `strsearch`
- SQL: `getSqlData(queryString)`
- Objects: `getObjects("MxClass", whereClause)`,
           `getObjectIdByCode("CLASS", code, type)`
- Params / lists: `getparam`, `GET_PARAM_LIST`, `getListItemId`
- Services: `callService(name, args)`

## When writing regex-based checks
- Scripts may contain CDATA artifacts, mixed line endings, and French
  inline comments.
- Loop keyword set: `for | foreach | while | do | until`.
- Log keyword set:  `msginfo | msgerror | msgwarn` (case-insensitive, per
  function-name case rule above).
- SQL verbs inside strings: `SELECT | INSERT | UPDATE | DELETE`
  (case-insensitive).
- Both assignment forms to match: `:=` and `?=`.
- `if | while | do | until` condition is `<keyword>\s*\((.*?)\)`.

## Anti-patterns already implemented in `reviewer.py`
Generic names (`tmp`, `varX`, `temp`), missing `USER_COMMENT`, verbose logs
inside loops, always-true/false conditions, dead code after terminators,
SQL calls inside loops, nested loops, duplicate/similar queries.

## Anti-patterns still to implement (from `docs/SPEC.md` — Must Have)
- Unbounded / trivially-infinite loops
- Multiple reads of the same object field without local caching
- Null-value handling around object field access (remember: assignment via
  `obj.FIELD[COND]` auto-creates, so "null guard" doesn't apply the same
  way as in other languages)
- Hardcoded sensitive literals (IDs, URLs, passwords)
- Missing `try { } onerror { }` around `getSqlData`, `callService`,
  `getObjects`
- Division by zero
- Cross-BizRule reference validation (does the called BR exist in the pack?)

## Anti-patterns the language spec enables (new candidates)
- `:=` where `?=` was likely intended, and vice versa (semantic bug).
- Variables differing only in case within the same rule (likely typo).
- `b := a` between array variables with no `arraycopy` after (aliasing
  bug).
- `foreach obj.TABLE do` immediately followed by code that relies on a
  specific cursor position (cursor reset is easy to forget).
