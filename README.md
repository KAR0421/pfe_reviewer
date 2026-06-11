# REVIEWER

Automated static analysis tool for NeoXam IMPRESS BizRule scripts.

REVIEWER analyzes BizRule scripts contained in IMPRESS `.pack` files, detects common quality issues across six families of checks — documentation, logic, performance, language and semantics, logging, and scope — and produces structured reports designed to integrate seamlessly into the team's code review workflow.

## Overview

REVIEWER takes one or more `.pack` files as input, extracts the BizRules they contain, transforms each script into an abstract syntax tree (AST), and applies a catalog of independent checks to detect defects. The output is available in four complementary formats: console (for local development), JSON (for downstream tooling), self-contained HTML (for archival), and Markdown (for Bitbucket pull request comments).

The tool is designed to integrate into the CI/CD pipeline: at each pull request modifying a `.pack` file, the analysis runs automatically and publishes its findings directly as a comment on the PR. It is strictly informative — it never blocks a build or fails a pull request.

## Requirements

- Python 3.10 or later
- No external runtime dependencies (uses standard library only)
- `pytest` for running the test suite

## Installation

Clone the repository and (optionally) create a virtual environment:

```bash
git clone https://bitbucket.my-nx.com/scm/im/impress-reviewer.git
cd impress-reviewer
python -m venv .venv
source .venv/bin/activate     # Linux / macOS
.venv\Scripts\activate        # Windows
```

No `pip install` is required — REVIEWER uses only the Python standard library.

## Usage

### Analyze a directory of `.pack` files

```bash
python main.py <directory>
```

The tool will scan the directory for `*.pack` and `*.pack*.xml` files and analyze each one.

### Analyze specific files (CI/CD mode)

```bash
python main.py --files <file1.pack> <file2.pack> ...
```

This mode is intended for CI/CD integration, where the Jenkins job passes the exact list of files modified in a pull request.

### Output options

- `--output report.json` — write findings as structured JSON
- `--quiet` — suppress console output (useful in CI mode)

### Examples

```bash
# Local analysis of the sample packs
python main.py .

# CI mode with JSON output
python main.py --files sample.pack --output report.json --quiet

# See all options
python main.py --help
```

## Running the tests

```bash
pytest -v
```

The test suite covers the tokenizer, parser, AST nodes, the engine, all check categories, and the four output reporters.

## Project structure

```
impress-reviewer/
├── main.py                          # CLI entry point
├── parser.py                        # Pack file (XML) parser
├── reviewer/
│   ├── ast/                         # Tokenizer, parser, AST nodes
│   ├── checks/                      # The catalog of quality checks
│   ├── engine/                      # Visit and dispatch engine
│   ├── integrations/                # Bitbucket REST integration
│   └── reporters/                   # Console, JSON, HTML, Markdown outputs
├── tests/                           # Unit tests and fixtures
└── sample.pack, sample.pack2        # Example pack files for local testing
```

## Author

Kalthoum Arfaoui — End-of-studies Project, NeoXam Tunisia, December 2025 – June 2026.
