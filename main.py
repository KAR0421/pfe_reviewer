from parser import extract_bizrules
from reviewer.engine.runner import run_review
from reviewer.reporters.console import print_report
from reviewer_legacy import review_bizrule as review_legacy


def _print_legacy(report: dict) -> None:
    """Print the legacy ``{name, issues}`` shape under a [legacy] label."""
    name = report["name"]
    issues = report["issues"]
    if not issues:
        print(f"[legacy] {name}: no issues found.")
        return
    print(f"[legacy] {name}: {len(issues)} issue(s)")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")


def main():
    xml_path = "sample.pack.xml"

    # Extract BizRules from XML
    bizrules = extract_bizrules(xml_path)

    print(f"BizRules found: {len(bizrules)}\n")

    # Review each BizRule with both pipelines side-by-side.
    for br in bizrules:
        print("----- BizRule -----")
        print(f"Name: {br.name}")
        print(f"Comment: {br.comment}")
        print(f"Scope: {br.scope}")
        print("Script Preview:", br.script[:200], "...\n")  # show first 200 chars

        legacy = review_legacy(br)
        new = run_review(br)

        _print_legacy(legacy)
        print_report(new, label="new")

        print("\n==============================\n")


if __name__ == "__main__":
    main()
