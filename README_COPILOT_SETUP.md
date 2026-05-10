# Copilot context files — drop-in bundle

This bundle gives GitHub Copilot the full context of the BizRule reviewer
project: what it does, the XML data format, the target scripting language,
the review scope, the AST-pipeline architecture, and a set of slash
commands for adding new checks and tests.

## What's in here

```
.github/
├── copilot-instructions.md                  always-on, attached to every chat
├── instructions/
│   ├── scripting-syntax.instructions.md     applies when editing reviewer/script files
│   ├── data-schema.instructions.md          applies when editing parser.py / pack fixtures
│   └── ast-pipeline.instructions.md         applies when editing reviewer/**
└── prompts/
    ├── new-review-check.prompt.md           /new-review-check — add a new AST check
    ├── add-test-case.prompt.md              /add-test-case — add fixture + test for a check
    └── review-script-manually.prompt.md     /review-script-manually — human-style review of a snippet

docs/
├── SPEC.md                                   spec + review scope + per-rule status
└── scripting-grammar.md                      authoritative language reference (from syntaxe.odt)
```

## How to install in your repo

1. Copy the `.github/` and `docs/` folders into your repo root.
2. Commit them. Copilot picks them up automatically in VS Code as soon
   as they're saved.
3. In VS Code Settings, make sure **"Code Generation: Use Instruction
   Files"** is enabled (default on in recent versions).
4. Verify: open Copilot Chat, send a message, and check the
   **References** list on the response — `copilot-instructions.md`
   should appear.

Your Python files (`main.py`, `parser.py`, the `reviewer/` package)
stay where they are. The bundle does not modify them.

## How each file type behaves

| File                            | When Copilot reads it                                             |
|---------------------------------|-------------------------------------------------------------------|
| `copilot-instructions.md`       | Every chat request in this repo.                                  |
| `*.instructions.md` with `applyTo` | Only when you're working on files matching the glob.           |
| `*.prompt.md`                   | Only when you invoke it with `/<name>` in Copilot Chat.           |

## The recommended workflow

### 0. First time — read the spec
Read `docs/SPEC.md` yourself first. Copilot has it too, and it will
operate assuming you've decided to follow that design. If you disagree
with anything, change the docs before starting — Copilot defers to them.

### 1. Add a new check
For any row marked `pending` in the SPEC §6 table:
```
/new-review-check
```
Give it the rule ID and target class name. The prompt will read the
SPEC row critically, propose AST hooks, wait for your confirmation,
then implement the check, add positive / negative / edge tests, and
flip the status row to `done`.

### 2. Add tests to an existing check
```
/add-test-case
```
Use this when you notice a check producing a wrong result, or when you
want to nail down a corner case. Add a fixture that reproduces, see
the test fail, then decide whether the bug is in the check or the
test. (The prompt stops at "test added" — fixing the check is a
separate task so you stay in control.)

### 3. Ad-hoc human-style review
```
/review-script-manually
```
Paste a BizRule's `IMPACT` content; Copilot reviews it against the
spec and your grammar reference.

## Editing advice

- `copilot-instructions.md` is sent with **every** request. Keep it
  short and focused on identity + architecture + DON'Ts. Push detail
  down into `docs/` and the path-scoped instructions files.
- `*.instructions.md` files can be as long as needed — they're only
  loaded when their glob matches.
- Prompt files work best when they ask for the small number of inputs
  they genuinely need, then rely on the instructions files for the
  "how".
- When the design evolves, update `docs/SPEC.md` first, then the
  relevant `.instructions.md` files, then write code. Copilot is most
  useful when the docs lead.

## Verifying Copilot is using the context

In VS Code Copilot Chat, send a message and look at the **References**
panel on the reply. You should see:
- `copilot-instructions.md` on every reply.
- The relevant `*.instructions.md` files when their glob matches the
  file you're editing.
- Any prompt file you invoked.

If those aren't showing up, Settings Sync may have an outdated value
for `chat.instructionsFilesLocations`, or "Use Instruction Files" may
be disabled.

## Open questions

These are documented in `docs/SPEC.md` §9 and shape the later
milestones:
- Authoritative list of valid object / class / list names (for SR050
  dependency resolution).
- Which `TRIGGER_TYPE` enum values matter for SR062.
- Regex catalogue for hardcoded-secrets detection (SR040), or
  agreement to write your own.
- Source of "previous version" for version-diff checks (SR080–SR082):
  git commit, prior pack, or a versioned store.

Answering them earlier saves rework later.
