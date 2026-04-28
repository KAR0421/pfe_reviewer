# Copilot context files — drop-in bundle

This bundle gives GitHub Copilot the full context of your BizRule reviewer
project: what it does, the XML data format, the target scripting language,
the review scope, the target architecture (AST pipeline), and a set of
slash commands that drive the migration and new checks.

## What's in here

```
.github/
├── copilot-instructions.md                  always-on, attached to every chat
├── instructions/
│   ├── scripting-syntax.instructions.md     applies when editing reviewer/script files
│   ├── data-schema.instructions.md          applies when editing parser/xml_loader
│   ├── ast-pipeline.instructions.md         applies when editing reviewer/** (the new pipeline)
│   └── reviewer.instructions.md             applies when editing reviewer_legacy.py ONLY (frozen)
└── prompts/
    ├── scaffold-pipeline.prompt.md          /scaffold-pipeline — bootstrap the AST pipeline
    ├── migrate-check.prompt.md              /migrate-check — move a legacy check to AST
    ├── new-review-check.prompt.md           /new-review-check — add a brand-new AST check
    ├── add-test-case.prompt.md              /add-test-case — add fixture + test for a check
    └── review-script-manually.prompt.md     /review-script-manually — human-style review of a snippet

docs/
├── SPEC.md                                   full spec + review scope + migration status table
├── scripting-grammar.md                      authoritative language reference (from syntaxe.odt)
└── adr/
    └── 0001-reviewer-architecture.md         the design decision record for the AST pipeline
```

## How to install in your repo

1. Copy the `.github/` and `docs/` folders into your repo root.
2. Commit them. Copilot picks them up automatically in VS Code / Visual
   Studio / JetBrains as soon as they're saved.
3. In VS Code Settings, make sure **"Code Generation: Use Instruction
   Files"** is enabled (default on in recent versions).
4. Verify: open Copilot Chat, send a message, and check the
   **References** list on the response — `copilot-instructions.md`
   should appear.

Your Python files (`main.py`, `parser.py`, `preprocessor.py`,
`reviewer.py`, `xml_loader.py`) stay at the repo root. The bundle does
not modify them.

## How each file type behaves

| File                            | When Copilot reads it                                             |
|---------------------------------|-------------------------------------------------------------------|
| `copilot-instructions.md`       | Every chat request in this repo.                                  |
| `*.instructions.md` with `applyTo` | Only when you're working on files matching the glob.           |
| `*.prompt.md`                   | Only when you invoke it with `/<name>` in Copilot Chat.           |

## The recommended workflow

### 0. First time — understand what Copilot knows
Read `docs/SPEC.md` and `docs/adr/0001-reviewer-architecture.md` yourself
first. Copilot has them too, and it will operate assuming you've decided
to follow that design. If you disagree with anything, change the docs
before starting — Copilot defers to them.

### 1. Bootstrap the AST pipeline
In Copilot Chat, invoke:
```
/scaffold-pipeline
```
This is a **multi-phase** prompt. It will pause between phases — do
**not** tell Copilot to do everything in one shot. Run tests between
phases and confirm each layer works before moving on. Outcome:

- `reviewer.py` renamed to `reviewer_legacy.py` (preserved, frozen).
- New `reviewer/` package with tokenizer, parser, AST nodes, engine,
  and one real check (`SqlInLoopCheck` — SR030).
- `main.py` runs both pipelines side-by-side.
- Tests for tokenizer, parser, engine, and the first check.

### 2. Migrate legacy checks one at a time
For each row in the Migration Status table in `docs/SPEC.md`:
```
/migrate-check
```
Give it the legacy function name, rule ID, and target class name
(all three are in the table). The prompt will:
- Read the legacy function and summarize what it does.
- Propose which AST visitor methods the new check needs.
- Implement the check.
- Add positive / negative / edge / diff tests.
- Update the Migration Status table row to `done`.

**Don't** delete `reviewer_legacy.py` yourself. Once every row is
`done` and diff-tests are clean across every pack fixture, run:
```
Please delete reviewer_legacy.py and remove the parallel execution
path from main.py. The Migration Status table is fully green.
```

### 3. Add brand-new checks (no legacy counterpart)
For the new rules from `syntaxe.odt` (SR055–SR058), the remaining
Must-Have security/dependency checks (SR040–SR043, SR050), or anything
else:
```
/new-review-check
```
This prompt creates the check directly in the AST pipeline — no legacy
version is created.

### 4. Patch a check that's misbehaving
```
/add-test-case
```
Use this when you notice a check producing a wrong result. Add a
fixture that reproduces, see the test fail, then decide whether the
bug is in the check or the test. (The prompt stops at "test added" —
fixing the check is a separate task so you stay in control.)

### 5. Ad-hoc human-style review
```
/review-script-manually
```
Paste a BizRule's `IMPACT` content; Copilot reviews it against the
spec and your grammar reference. Useful for testing Copilot's
understanding of the spec while the pipeline is mid-build.

## Editing advice

- `copilot-instructions.md` is sent with **every** request. Keep it
  short and focused on identity + target architecture + DON'Ts. Push
  detail down into `docs/` and the path-scoped instructions files.
- `*.instructions.md` files can be as long as needed — they're only
  loaded when their glob matches.
- Prompt files work best when they ask for the small number of inputs
  they genuinely need, then rely on the instructions files for the
  "how".
- When the design evolves, update the ADR and `docs/SPEC.md` first,
  then the relevant `.instructions.md` files, then write code. Copilot
  is most useful when the docs lead.

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

## Open questions you still need to answer

These are documented in `docs/SPEC.md` §9 and will shape the later
milestones:
- Authoritative list of valid object / class / list names (for SR050
  dependency resolution).
- Which `TRIGGER_TYPE` enum values matter for SR062.
- Regex catalogue for hardcoded-secrets detection (SR040), or agreement
  to write your own.
- Source of "previous version" for version-diff checks (SR080–SR082):
  git commit, prior pack, or a versioned store.

Answering them earlier saves rework later.
