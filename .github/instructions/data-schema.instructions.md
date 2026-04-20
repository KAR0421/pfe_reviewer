---
name: "XML Pack Data Format"
description: "Structure of the .pack XML files and how to safely extract BizRules"
applyTo: "parser.py,xml_loader.py,tests/fixtures/**/*.xml"
---

# XML `.pack` data format

Pack files are NeoXam DataHub export packages. The formal schema is in
`schema.xml` (XSD). Real packs do **not** strictly conform — they contain
CDATA payloads with unescaped `<`, `>`, `&`, and even stray XML-like text
inside scripts. This is why `parser.py` uses regex instead of a straight
`ElementTree.parse`.

## Top-level shape
```xml
<?xml version='1.0' encoding="UTF-8" ?>
<HEAD>
  <PACKAGE>...</PACKAGE>
  <n>...</n>
  <BUILD_DATE>YYYYMMDD</BUILD_DATE>
  <LEVEL>OPTIONAL|MANDATORY</LEVEL>
  <RELEASE>x.y.z</RELEASE>
  <CREATOR>username</CREATOR>
</HEAD>
<BODY>
  <RESULT MODE="XML" ACTION="GETOBJECTS" VERSION="2" CHARSET="UTF8">
    <SMARTRULE FIND="RULE_CODE='...'" USER="..." UPDATE_DATE="..." LABEL="...">
       ...
    </SMARTRULE>
    <SMARTRULE .../>
    ...
  </RESULT>
</BODY>
```
Note: the document has **no single root element** in practice (`HEAD` and
`BODY` are siblings at the top level). `xml_loader.py` works around this by
wrapping content in a synthetic `<ROOT>`.

## `<SMARTRULE>` — the BizRule
Attributes on the opening tag:
- `FIND="RULE_CODE='...'"` → used as `BizRule.scope`
- `USER`, `UPDATE_DATE`, `UPDATE_TIME`, `LABEL` → metadata

Key child elements (from `schema.xml`):
- `ACTIVE`                         — Y/N
- `CONDITION`                      — condition expression (often a reference)
- `DESCRIPTION`                    — optional, often empty
- **`IMPACT`**                     — **the script** (CDATA) ← the review target
- `PRIVACY_LEVEL`, `RULE_CATEGORY`, `RULE_GROUP`, `RULE_STATUS`,
  `RULE_STATUS_AVAILABILITY`, `RULE_TYPE` — enumerations, see `schema.xml`
- `RULE_CODE`                      — the rule identifier (CDATA)
- **`USER_COMMENT`**               — user documentation (CDATA)
- `SMARTRULE_NAME` (repeating)     — per-language display names (0=EN, 1=FR, ...)
- `SMARTRULE_TRIGGER` (repeating)  — trigger config (`TRIGGER_TYPE`, `TRIGGER_OBJECT`)
- `SMARTRULE_WFLINK` (repeating)   — workflow links

## Extraction gotchas
- `RULE_CODE`, `USER_COMMENT`, `IMPACT`, `DESCRIPTION`, `CONDITION` are all
  **CDATA-wrapped**. Strip `<![CDATA[ ... ]]>` when extracting.
- CDATA blocks may themselves contain `<`, `>`, `&`, `<!--...-->` and even
  substrings that look like XML tags. Never run an XML parser over a pack
  without first sanitizing (see `xml_loader.py::replace_impact`).
- Some elements appear empty with a trailing space: `<DESCRIPTION ></DESCRIPTION>`.
- `FIND` attribute uses single quotes around the value: `FIND="RULE_CODE='FOO'"`.
- Packs may contain free-floating HTML-style comments (`<!-- ... -->`) at the
  top of `<BODY>` and between rules.

## Canonical mapping to the `BizRule` dataclass
| BizRule field | XML source                          |
|---------------|-------------------------------------|
| `name`        | `<RULE_CODE>` (CDATA, stripped)     |
| `comment`     | `<USER_COMMENT>` (CDATA, stripped)  |
| `scope`       | `FIND` attribute on `<SMARTRULE>`   |
| `script`      | `<IMPACT>` (CDATA, stripped)        |

When adding fields (e.g. `description`, `trigger_type`, `trigger_object`,
`rule_category`, `update_date`, `user`), extend `BizRule.__init__`
**in `parser.py`** and update this table.

## Two loader styles in the repo
1. `parser.py` — regex-only, no real XML parsing. Robust to malformed packs,
   fragile if tag layout changes. Currently used by `main.py`.
2. `xml_loader.py` — sanitizes `<IMPACT>` to placeholders, wraps in `<ROOT>`,
   parses with `ElementTree`, then restores the scripts. Cleaner model, but
   not yet wired into `main.py`.

If consolidating, prefer the sanitize-then-parse model (#2). Do not attempt
a third loader without a clear reason.
