# BizRule scripting language — grammar reference

> Source: official syntax specification (`syntaxe.odt`) + patterns observed in
> sample packs (`sample_pack.xml`, `sample_pack2.xml`). This document is the
> authoritative reference every review check should consult.

## 1. Variables and values

### Assignment
- **`:=`** — plain assignment.
- **`?=`** — conditional assignment: assigns **only if** the variable is
  currently empty. Misuse (`?=` where plain `:=` was intended, or vice versa)
  is a semantic bug worth flagging.

### Case sensitivity
- **Variable names are case-sensitive** (`contrib` ≠ `Contrib`).
- **Function names are NOT case-sensitive** (`getSqlData` = `GETSQLDATA`).

A reviewer can legitimately warn on variables that differ only in case —
they look like typos.

### Base types
| Type    | Literal form         | Notes |
|---------|----------------------|-------|
| String  | `"..."` or `'...'`   | Both quote styles valid. Dates are strings. |
| Numeric | `nnn` or `nnn.ddd`   | Integer or decimal. |
| Object  | via `getObjects`, `getObjectIdByCode`, etc. | Carries a cursor per table (see §3). |
| Array   | via `array()`        | See §4. Reference semantics — watch `arraycopy`. |

### Boolean truthiness
- `0` and `""` are **false**.
- Everything else is truthy.
- No explicit `true` / `false` keywords in the spec.

## 2. Expressions and operators

| Category    | Operators              |
|-------------|------------------------|
| Arithmetic  | `+`, `-`, `*`, `/`     |
| Comparison  | `=`, `!=`, `<`, `<=`, `>`, `>=` |
| Logical     | `and`, `or`            |
| String concat | `+`                  |

**Equality is `=`, not `==`. Assignment is `:=`, not `=`.** The parser won't
confuse them, but a reviewer should still watch conditions for `:=`-where-`=`
intended and vice versa.

## 3. Objects

### Field access
```
obj.FIELDNAME               // read
obj.FIELDNAME := value      // write
```

### Multi-row fields (table cursors)
Each object variable maintains a **cursor per table**. Accessing
`obj.TABLE.FIELD` respects that cursor. Assigning an object to a new
variable **gives the new variable its own cursors**:
```
copy := obj;   // copy has independent cursors
```

### Row selection with condition
```
obj.FIELDNAME[COND_FIELD = value and OTHER = value2]
```
Rules:
- Only `=` as comparator.
- Only `and` as logical operator.
- Condition fields must belong to the same table as `FIELDNAME`.
- Right-hand sides may be string literals, numeric literals, or variables.

### Auto-create on assignment (⚠️ surprising)
When the condition form is used to **assign**:
```
obj.FIELDNAME[KEY = "X"] := someValue
```
and no matching record exists, a **new record is created** with the values
given in the condition. Flag surprise-creates when unintentional.

### Reference coercion
Comparing an object/list-field to a string silently converts the string to
its reference id. Same happens on assignment via that syntax — with the
auto-create behavior above.

## 4. Arrays

```
a := array();           // empty array; first index is 0
a[0] := "first";
n := arraysize(a);      // length; valid indices are 0..n-1
```

### Reference vs copy (⚠️ common footgun)
```
b := a;            // b IS a — mutations in b affect a
c := arraycopy(a);   // c is an independent copy
```
`b := a` without a subsequent `arraycopy` is a good reviewer candidate when
`a` is known to be an array.

The product also provides a broader "Array functions" catalog beyond these.

## 5. Statements and code structure

- Statements separated by `;`.
- Blocks wrapped in `{ ... }`.
- Single-statement branches are valid everywhere blocks are — no braces
  required.

### Conditional
```
if (expr) stmt;
if (expr) stmt1; else stmt2;
if (expr) { block } else { block }
```

### Loops
```
for (init; cond; step) stmt;
for var := n to   m do stmt;    // counting up
for var := n downto m do stmt;  // counting down
foreach o in list do stmt;
foreach obj.TABLE do stmt;      // walks the table using the object cursor
while (expr) stmt;
do stmt while (expr);
```
All bodies accept a single statement or a `{ ... }` block.

### End-of-execution statements
| Keyword  | Form                            | Effect |
|----------|---------------------------------|--------|
| `return` | `return;` or `return expr;`     | Exits the rule, optionally with a value |
| `skip`   | `skip [expr or message];`       | Skips the current item |
| `abort`  | `abort [expr or message];`      | Aborts the rule with an error |

Non-empty, non-`}` lines immediately following one of these are dead code
(checked by `SR021`).

## 6. Error handling

```
try {
    obj.set("MY_FIELD", 0, 0);
}
onerror {
    if (error.isType("dqc")) {
        // handle dqc-specific error
    }
}
```

Rules:
- A `try` block must be immediately followed by an `onerror` block — the
  kernel raises a syntax error otherwise.
- Both accept a brace-block or a single statement.
- Inside `onerror`, the implicit variable **`error`** (type `ScriptError`)
  holds the error; check its type with `error.isType("...")`.

### Error types (`error.isType(...)`)
| Type         | Meaning |
|--------------|---------|
| `dqc`        | Data-quality-check violation |
| `integrity`  | Integrity rule violation (e.g. uniqueness) |
| `abort`      | Script aborted via `abort` |
| `script`     | Other script-statement errors |
| `internal`   | Kernel-level technical error |
| `server`     | Server-side error |
| `dictionary` | Unknown field or table |

This is what `SR043` (missing error handling around risky calls) relies on:
a call to `getSqlData` / `callService` / `getObjects` that sits outside any
`try { ... }` block is flaggable.

## 7. Function and method calls

### Plain function call
```
result := function(arg1, arg2, ...);
```

### Method call on an object
```
result := obj.method(arg1, arg2, ...);
```

### User-defined **methods**
A rule with:
- A target object configured.
- Trigger = `INTERNAL_PROCESSING`.
- Trigger argument = the method name.
- Arguments arrive in `arg1`, `arg2`, …; total count in `argcount`.
- No argument-count validation by the kernel.

### User-defined **functions**
Same as methods, but **no** target object is configured.

## 8. Reserved keywords

Mainly control-flow:
```
if, else, while, until, for, in, do, foreach, return, skip, abort, ...
```
(The official spec uses `...` — not exhaustive. `try` / `onerror` are
effectively reserved too.)

## 9. Execution context — implicit variables

Depends on how the rule is invoked.

| Invocation                                | Implicit variables                     | Failure behavior |
|-------------------------------------------|----------------------------------------|------------------|
| Trigger on object modification            | `obj`, `newvalue`                      | Previous modifications **kept** on failure |
| Action on a single object (mono-object)   | `obj`                                  | Changes rolled back on failure |
| Action on multi-objects / autonomous rule | `objects` (array), `objectset` (from query screen) | Rolled back on failure |
| Action on a pool (object-group rule)      | `master_object`, `obj1`, `objectset`   | — |
| Object method (user-defined)              | `obj`, `arg1`…`argN`, `argcount`       | Depends on caller |
| Function (user-defined)                   | `arg1`…`argN`, `argcount`              | Depends on caller |

Notes:
- The spec sometimes writes `args1` — read as `arg1` (spec typo).
- A script's **return value** is either `return expr;` or a bare expression
  at the end of the script.
- `obj1` appears both as "first method argument" in some rules and as "the
  triggering object" in pool rules. Don't conflate the two when reviewing.

## 10. Comments and conventions (observed in real packs)

Comment form (not in the spec but uniform in practice):
```
// single-line comment
```
No block-comment form has been seen. Typical patterns:
- Author/date banners: `// ADF - 13/02/2024 ...`
- Ticket markers inline: `//IMPRESS-9892`
- `BEGIN/END` feature-gated blocks:
  ```
  //BEGIN01-IMPRESS-9432 ...
  //END01-IMPRESS-9432
  ```
- Mixed French and English.

## 11. Common built-ins (observed — non-exhaustive)

### Logging
`msginfo(...)`, `msgerror(...)`, `msgwarn(...)`

### Arrays
`array()`, `arraysize(a)`, `arraycopy(a)`, `arrayappend(a, v)`, `strsearch(a, v)`

### SQL
`getSqlData(queryString)` — runs raw SQL built by `+`-concatenation.

### Objects / metadata
`getObjects(className, whereClause)`, `getObjectIdByCode(class, code, type)`,
`getparam(key)`, `GET_PARAM_LIST(listCode)`, `getListItemId(listCode, value)`

### Services
`callService(serviceName, args)`

## 12. Checklist for reviewer code that parses scripts

- `//` introduces a comment to end-of-line; scan but do not analyze content.
- Scripts mix inline `if` with braced blocks within the same rule.
- Loop keywords to match: `for`, `foreach`, `while`, `do`, `until`.
- Terminators: `return`, `abort`, `skip`.
- Assignment tokens (both forms): `:=`, `?=`.
- A call is "error-safe" iff it is inside a `try { ... }` with a matching
  `onerror { ... }`.
- Array-reference bugs show up as `b := a` between array-typed variables
  with no intervening `arraycopy`.
- Case-sensitive variable matching, case-insensitive function matching.
