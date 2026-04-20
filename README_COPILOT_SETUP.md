# Copilot context files — drop-in bundle

This bundle gives GitHub Copilot the full context of your BizRule reviewer
project: what it does, the XML data format, the target scripting language,
the review scope, and conventions for adding new checks.

## What's in here

```
.github/
├── copilot-instructions.md                  always-on, attached to every chat
├── instructions/
│   ├── scripting-syntax.instructions.md     applies when editing reviewer/script files
│   ├── data-schema.instructions.md          applies when editing parser/xml_loader
│   └── reviewer.instructions.md             applies when editing reviewer.py or tests
└── prompts/
    ├── new-review-check.prompt.md           /new-review-check in chat
    ├── add-test-case.prompt.md              /add-test-case in chat
    └── review-script-manually.prompt.md     /review-script-manually in chat

docs/
├── SPEC.md                                   full project spec + review scope + rule IDs
└── scripting-grammar.md                      language reference (syntax.txt goes here)
```

## How to install in your repo

1. Copy the `.github/` and `docs/` folders into your repo root.
2. Commit them. Copilot picks them up automatically in VS Code / Visual Studio /
   JetBrains as soon as they're saved.
3. Verify in VS Code: open Copilot Chat, send a message, and check the
   **References** list on the response — `copilot-instructions.md` should
   appear there.
4. In VS Code Settings, make sure **"Code Generation: Use Instruction Files"**
   is enabled (default on in recent versions).

## How each file type behaves

| File                            | When Copilot reads it                                             |
|---------------------------------|-------------------------------------------------------------------|
| `copilot-instructions.md`       | Every chat request in this repo.                                  |
| `*.instructions.md` with `applyTo` | Only when you're working on files matching the glob.           |
| `*.prompt.md`                   | Only when you invoke it with `/<name>` in Copilot Chat.           |

## Things you still need to do

### 1. Paste `syntax.txt` into the grammar file
Open `docs/scripting-grammar.md`. The top has a TODO. Replace the placeholder
content with the authoritative syntax. Keep (or expand) the "Built-ins",
"Style conventions", and "Unknown / to confirm" sections — they're useful
whether or not they end up in the official spec.

### 2. Review `docs/SPEC.md`
I drafted rule IDs (`SR001`–`SR092`) matching the Must/Should Have scope in
`code_review_scope.pdf`. Assigning stable IDs now makes the later migration
to a `Finding` dataclass trivial. Change them if you prefer a different
numbering.

### 3. Answer the open questions in SPEC.md §9
These will shape some Must-Have checks (dependency resolution, trigger
validation, version diff source).

### 4. Decide between `parser.py` and `xml_loader.py`
Today `main.py` uses `parser.py` (regex-only). `xml_loader.py` is the
cleaner approach (sanitize CDATA → wrap in root → parse with ElementTree →
restore scripts) but isn't wired in. Pick one and delete the other, then
update `.github/instructions/data-schema.instructions.md` accordingly.

### 5. Fix the small `main.py` issue
```python
xml_path = "sample.pack.xml"
```
should match your actual filename (`sample_pack.xml`). Not a Copilot issue,
just spotted while reading.

## Useful slash commands (VS Code)

Once the files are in place, in Copilot Chat:

- `/new-review-check` — scaffolds a new `check_*` function, registers it in
  `review_bizrule`, adds tests, updates the SPEC table.
- `/add-test-case` — adds a fixture + test for an existing check.
- `/review-script-manually` — pastes a script body and gets a human-shaped
  review back, following the spec.

You can also type `/create-prompt` in chat to have Copilot help you write
new prompt files, or `/init` to regenerate `copilot-instructions.md` from
your current codebase if it drifts out of date.

## Editing advice
- `copilot-instructions.md` is sent with **every** request. Keep it short
  and focused on identity + conventions + DON'Ts. Push detail down into
  `docs/` and link from there.
- `*.instructions.md` files can be as long as needed — they're only loaded
  when their glob matches.
- Prompt files are best when they ask for the small number of inputs they
  genuinely need, then rely on the instruction files for the "how".
