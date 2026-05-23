"""Entry point: review every ``*.pack*.xml`` in a directory.

Console output is the default. ``--output PATH`` additionally writes a
JSON report (see ``reviewer/reporters/json_reporter.py`` for the
schema). ``--quiet`` suppresses console output (combine with
``--output`` for headless CI use).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from parser import extract_bizrules
from reviewer.engine.runner import run_review
from reviewer.reporters import json_reporter
from reviewer.reporters.console import print_report


def _review_pack(xml_path: Path, *, quiet: bool):
    """Review a single pack. Returns ``(pack_file_name,
    [(bizrule, report), ...])`` for JSON aggregation; prints to stdout
    unless ``quiet`` is set.
    """
    bizrules = extract_bizrules(str(xml_path))
    if not quiet:
        print(f"##### Pack: {xml_path.name} #####")
        print(f"BizRules found: {len(bizrules)}\n")

    br_reports: list = []
    for br in bizrules:
        report = run_review(br, pack_bizrules=bizrules)
        br_reports.append((br, report))
        if not quiet:
            print("----- BizRule -----")
            print(f"Name: {br.name}")
            print(f"Comment: {br.comment}")
            print(f"Scope: {br.scope}")
            print("Script Preview:", br.script[:200], "...\n")
            print_report(report)
            print("\n==============================\n")

    return xml_path.name, br_reports


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="reviewer",
        description="Review every *.pack*.xml in a directory.",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to search for *.pack*.xml files (default: .)",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="Write findings as JSON to PATH (in addition to console).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output (use with --output for CI).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.path)
    pack_files = sorted(root.glob("*.pack*.xml"))
    if not pack_files:
        if not args.quiet:
            print(f"No .pack.xml files found in {root.resolve()}.")
        if args.output:
            json_reporter.write_json(
                json_reporter.to_json_dict(
                    [], directory=str(root.resolve())
                ),
                args.output,
            )
        return 0

    packs_with_reports = [
        _review_pack(p, quiet=args.quiet) for p in pack_files
    ]

    if args.output:
        data = json_reporter.to_json_dict(
            packs_with_reports, directory=str(root.resolve())
        )
        json_reporter.write_json(data, args.output)
        if not args.quiet:
            print(f"Wrote JSON report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


