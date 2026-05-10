"""Entry point: review every BizRule in a pack file."""
from __future__ import annotations

from parser import extract_bizrules
from reviewer.engine.runner import run_review
from reviewer.reporters.console import print_report


def main() -> None:
    xml_path = "sample.pack.xml"
    bizrules = extract_bizrules(xml_path)

    print(f"BizRules found: {len(bizrules)}\n")

    for br in bizrules:
        print("----- BizRule -----")
        print(f"Name: {br.name}")
        print(f"Comment: {br.comment}")
        print(f"Scope: {br.scope}")
        print("Script Preview:", br.script[:200], "...\n")

        report = run_review(br)
        print_report(report)

        print("\n==============================\n")


if __name__ == "__main__":
    main()

