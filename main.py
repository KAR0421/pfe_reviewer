from parser import extract_bizrules
from reviewer_legacy import review_bizrule as review_legacy

def main():
    xml_path = "sample.pack.xml"

    # Extract BizRules from XML
    bizrules = extract_bizrules(xml_path)

    print(f"BizRules found: {len(bizrules)}\n")

    # Review each BizRule
    for br in bizrules:
        print("----- BizRule -----")
        print(f"Name: {br.name}")
        print(f"Comment: {br.comment}")
        print(f"Scope: {br.scope}")
        print("Script Preview:", br.script[:200], "...\n")  # show first 200 chars

        # Run the reviewer
        report = review_legacy(br)

        if report["issues"]:
            print("Issues found:")
            for i, issue in enumerate(report["issues"], 1):
                print(f"{i}. {issue}")
        else:
            print("No issues found!")

        print("\n==============================\n")

if __name__ == "__main__":
    main() 