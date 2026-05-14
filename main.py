from pathlib import Path

from parser import extract_bizrules
from reviewer.engine.runner import run_review
from reviewer.reporters.console import print_report


def _review_pack(xml_path: Path) -> None:
    bizrules = extract_bizrules(str(xml_path))
    print(f"##### Pack: {xml_path.name} #####")
    print(f"BizRules found: {len(bizrules)}\n")

    for br in bizrules:
        print("----- BizRule -----")
        print(f"Name: {br.name}")
        print(f"Comment: {br.comment}")
        print(f"Scope: {br.scope}")
        print("Script Preview:", br.script[:200], "...\n")

        print_report(run_review(br, pack_bizrules=bizrules))

        print("\n==============================\n")


def main():
    pack_files = sorted(Path(".").glob("*.pack*.xml"))
    if not pack_files:
        print("No .pack.xml files found in the current directory.")
        return
    for xml_path in pack_files:
        _review_pack(xml_path)


if __name__ == "__main__":
    main()


